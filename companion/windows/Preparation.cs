using System.Globalization;
using System.IO.Compression;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace CremaCompanion;

internal sealed record Preparation(string Coffee, string Roast, string Roaster, string Mode,
    decimal Green, decimal Charge, decimal Drop, decimal Off, string Title, string Id,
    int Plan, int Row, DateTimeOffset Created, string ArchiveHash, Dictionary<string, byte[]> Data)
{
    internal const int FileLimit = 2_000_000;
    internal const int ArchiveLimit = 8_000_000;
    private static readonly HashSet<string> Allowed = new(StringComparer.Ordinal)
        { "manifest.json", "reference.alog", "alarms.alrm", "roast-title.txt", "READ-ME.txt", "Prepare-Artisan.ps1", "Prepare-Artisan.cmd" };
    internal static readonly string[] Required = ["reference.alog", "alarms.alrm", "roast-title.txt"];

    internal static Preparation Read(string path, DateTimeOffset now)
    {
        if(string.IsNullOrWhiteSpace(path) || Path.GetFullPath(path).StartsWith("\\\\",StringComparison.Ordinal))
            throw new InvalidDataException("Choose a local preparation ZIP. Network paths are not supported by this pilot.");
        using var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read);
        if (stream.Length > ArchiveLimit) throw new InvalidDataException("This preparation ZIP is too large.");
        string archiveHash = Convert.ToHexString(SHA256.HashData(stream)).ToLowerInvariant();
        stream.Position = 0;
        using var zip = new ZipArchive(stream, ZipArchiveMode.Read);
        if (zip.Entries.Count is < 4 or > 7) throw new InvalidDataException("Unsupported preparation ZIP contents.");
        var files = new Dictionary<string, byte[]>(StringComparer.Ordinal);
        long total = 0;
        foreach (var entry in zip.Entries)
        {
            if (!Allowed.Contains(entry.FullName) || files.ContainsKey(entry.FullName))
                throw new InvalidDataException("Unexpected, duplicate or nested file in the preparation.");
            int limit = entry.FullName == "manifest.json" ? 65536 : FileLimit;
            if (entry.Length > limit || (total += entry.Length) > ArchiveLimit)
                throw new InvalidDataException("The preparation exceeds its file limits.");
            using var input = entry.Open();
            using var output = new MemoryStream();
            byte[] buffer = new byte[8192];
            int count;
            while ((count = input.Read(buffer)) != 0)
            {
                if (output.Length + count > limit) throw new InvalidDataException("An expanded file is too large.");
                output.Write(buffer, 0, count);
            }
            files.Add(entry.FullName, output.ToArray());
        }
        using var manifest = Parse(files.GetValueOrDefault("manifest.json") ?? throw new InvalidDataException("Missing manifest."));
        var m = manifest.RootElement;
        if (m.GetProperty("format").GetInt32() != 1 || Text(m,"profile_format",40) != "artisan-python-literal")
            throw new InvalidDataException("Prepare a fresh package using the current Crema portal.");
        foreach (var name in Required)
        {
            if (!files.TryGetValue(name, out var raw)) throw new InvalidDataException("Missing " + name);
            string expected = m.GetProperty("files").GetProperty(name).GetString() ?? "";
            string actual = Convert.ToHexString(SHA256.HashData(raw)).ToLowerInvariant();
            if (expected != actual) throw new InvalidDataException("Checksum mismatch: " + name);
        }
        string mode = Text(m,"mode",10);
        if (mode is not ("first" or "second")) throw new InvalidDataException("Choose First or Second in Crema.");
        string title = Text(m,"roast_title",300);
        if (new UTF8Encoding(false,true).GetString(files["roast-title.txt"]).TrimEnd('\r','\n') != title)
            throw new InvalidDataException("The title does not match the manifest.");
        decimal green = Number(m,"green_oz"), charge = Number(m,"charge"), drop = Number(m,"drop"), off = Number(m,"off");
        if (green <= 0 || green > 100000 || charge < 32 || drop <= charge || off != drop + .1m || off > 600)
            throw new InvalidDataException("Invalid green weight or Fahrenheit alarm targets.");
        string roast=Text(m,"roast_level",30);
        if (!new[]{"Light","Light/Medium","Medium","Medium/Dark","Dark","French"}.Contains(roast))
            throw new InvalidDataException("Unsupported roast level.");
        string id=Text(m,"preparation_id",36);
        if (!Guid.TryParseExact(id,"D",out _)) throw new InvalidDataException("Missing preparation identity.");
        int plan=m.GetProperty("plan_id").GetInt32(), row=m.GetProperty("planned_batch_id").GetInt32();
        if(plan<=0 || row<=0) throw new InvalidDataException("Invalid plan or load number.");
        if (!DateTimeOffset.TryParse(Text(m,"created_utc",64),CultureInfo.InvariantCulture,DateTimeStyles.None,out var created))
            throw new InvalidDataException("Invalid preparation date.");
        if (created.Offset != TimeSpan.Zero || now-created>TimeSpan.FromHours(24) || created-now>TimeSpan.FromMinutes(5))
            throw new InvalidDataException("This preparation is old or its date is invalid. Download it again from Crema.");
        using var alarmDoc = Parse(files["alarms.alrm"]);
        var a=alarmDoc.RootElement;
        CheckArray(a,"alarmactions",16,13,15);CheckArray(a,"alarmguards",-1,0,1);
        CheckArray(a,"alarmnegguards",-1,-1,-1);CheckArray(a,"alarmtimes",-1,0,6);
        CheckArray(a,"alarmflags",1,1,1);CheckArray(a,"alarmoffsets",0,0,0);
        CheckArray(a,"alarmconds",1,1,1);CheckArray(a,"alarmsources",1,1,1);
        CheckArray(a,"alarmbeep",0,0,0);CheckArray(a,"alarmtemperatures",charge,drop,off);
        if (!a.GetProperty("alarmstrings").EnumerateArray().Select(x=>x.GetString()).SequenceEqual(new[]{"Charge","Drop","Off"}))
            throw new InvalidDataException("Unexpected alarm names.");
        // Only data files survive validation. Scripts from the ZIP are never extracted or run.
        var payload = Required.ToDictionary(name=>name,name=>files[name]);
        return new(Text(m,"coffee",180),roast,Text(m,"roaster",40),mode,green,charge,drop,off,title,id,plan,row,created,archiveHash,payload);
    }
    internal void CheckAge(DateTimeOffset now)
    {
        if(now-Created>TimeSpan.FromHours(24) || Created-now>TimeSpan.FromMinutes(5))
            throw new InvalidDataException("This preparation expired. Download it again from Crema.");
    }
    internal string Materialize(string stateRoot)
    {
        var root=Path.Combine(stateRoot,"preparations");Directory.CreateDirectory(root);
        var dir=Path.Combine(root,Guid.NewGuid().ToString("N"));Directory.CreateDirectory(dir);
        foreach(var (name,raw) in Data) File.WriteAllBytes(Path.Combine(dir,name),raw);
        return dir;
    }
    private static JsonDocument Parse(byte[] data)
    {
        var doc=JsonDocument.Parse(data,new JsonDocumentOptions{MaxDepth=20});
        try{Unique(doc.RootElement);return doc;}catch{doc.Dispose();throw;}
    }
    private static void Unique(JsonElement value)
    {
        if(value.ValueKind==JsonValueKind.Object)
        {
            var keys=new HashSet<string>(StringComparer.Ordinal);
            foreach(var p in value.EnumerateObject()){if(!keys.Add(p.Name))throw new InvalidDataException("Duplicate JSON field.");Unique(p.Value);}
        }
        else if(value.ValueKind==JsonValueKind.Array)foreach(var item in value.EnumerateArray())Unique(item);
    }
    private static string Text(JsonElement value,string key,int max)
    {
        var text=value.GetProperty(key).GetString();
        if(string.IsNullOrWhiteSpace(text)||text.Length>max||text.Any(char.IsControl))throw new InvalidDataException("Invalid "+key);
        return text;
    }
    private static decimal Number(JsonElement value,string key)
    {
        var x=value.GetProperty(key);
        string text=x.ValueKind==JsonValueKind.String?x.GetString()!:x.GetRawText();
        if(!decimal.TryParse(text,NumberStyles.AllowLeadingSign|NumberStyles.AllowDecimalPoint,CultureInfo.InvariantCulture,out decimal n))
            throw new InvalidDataException("Invalid "+key);
        return n;
    }
    private static void CheckArray(JsonElement a,string key,params decimal[] expected)
    {
        if(!a.GetProperty(key).EnumerateArray().Select(x=>x.GetDecimal()).SequenceEqual(expected))
            throw new InvalidDataException("Unexpected alarm settings: "+key);
    }
}
