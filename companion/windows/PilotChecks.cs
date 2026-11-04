using System.IO.Compression;
using System.IO.Pipes;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace CremaCompanion;

internal static class PilotChecks
{
    internal static int Run(string reportPath)
    {
        var checks=new List<string>();
        try
        {
            string root=Path.Combine(Path.GetDirectoryName(Path.GetFullPath(reportPath))!,"fixture-"+Guid.NewGuid().ToString("N"));Directory.CreateDirectory(root);
            string Make(string name,Action<Dictionary<string,object?>>? change=null,string? extra=null,bool duplicate=false,bool corrupt=false)
            {
                string title="Demo Hearth 40.0oz 1 FC";
                var payload=new Dictionary<string,byte[]>{["reference.alog"]=Encoding.UTF8.GetBytes("{'mode': 'F', 'title': 'Demo reference', 'timex': [0.0, 1.0], 'temp1': [350.0, 351.0], 'temp2': [300.0, 301.0], 'extratemp1': [], 'extratemp2': []}"),["roast-title.txt"]=Encoding.UTF8.GetBytes(title+"\n")};
                payload["alarms.alrm"]=JsonSerializer.SerializeToUtf8Bytes(new{alarmflags=new[]{1,1,1},alarmguards=new[]{-1,0,1},alarmnegguards=new[]{-1,-1,-1},alarmtimes=new[]{-1,0,6},alarmoffsets=new[]{0,0,0},alarmconds=new[]{1,1,1},alarmsources=new[]{1,1,1},alarmtemperatures=new[]{350m,440m,440.1m},alarmactions=new[]{16,13,15},alarmbeep=new[]{0,0,0},alarmstrings=new[]{"Charge","Drop","Off"}});
                var manifest=new Dictionary<string,object?>{{"format",1},{"profile_format","artisan-python-literal"},{"mode","first"},{"roast_title",title},{"coffee","Demo Hearth"},{"roast_level","Medium"},{"roaster","Demo Small"},{"green_oz","40.0"},{"charge","350.0"},{"drop","440.0"},{"off","440.1"},{"plan_id",1},{"planned_batch_id",1},{"preparation_id",Guid.NewGuid().ToString()},{"created_utc",DateTimeOffset.UtcNow.ToString("O")},{"files",payload.ToDictionary(x=>x.Key,x=>Convert.ToHexString(SHA256.HashData(x.Value)).ToLowerInvariant())}};
                change?.Invoke(manifest);if(corrupt)payload["reference.alog"]=[1,2,3];
                string path=Path.Combine(root,name+".zip");using var zip=ZipFile.Open(path,ZipArchiveMode.Create);
                void Entry(string key,byte[] value){using var stream=zip.CreateEntry(key).Open();stream.Write(value);}
                Entry("manifest.json",JsonSerializer.SerializeToUtf8Bytes(manifest));foreach(var p in payload)Entry(p.Key,p.Value);
                if(extra!=null)Entry(extra,Encoding.UTF8.GetBytes("This must never run."));
                if(duplicate)Entry("reference.alog",payload["reference.alog"]);
                return path;
            }
            void Reject(string name,Action<Dictionary<string,object?>>? change=null,string? extra=null,bool duplicate=false,bool corrupt=false)
            {
                string path=Make(name,change,extra,duplicate,corrupt);bool refused=false;
                try{Preparation.Read(path,DateTimeOffset.UtcNow);}catch{refused=true;}
                if(!refused)throw new Exception("Did not reject "+name);checks.Add(name);
            }
            var valid=Preparation.Read(Make("valid",extra:"Prepare-Artisan.ps1"),DateTimeOffset.UtcNow);
            if(valid.Coffee!="Demo Hearth" || valid.Green!=40 || valid.Off!=440.1m || valid.Data.Count!=3)throw new Exception("Valid preparation differs.");
            string extracted=valid.Materialize(root);
            if(!Directory.GetFiles(extracted).Select(Path.GetFileName).Order().SequenceEqual(Preparation.Required.Order()))throw new Exception("Unexpected extracted scripts/files.");
            checks.Add("valid-current-preparation-and-data-only-extraction");
            Reject("checksum-tampering",corrupt:true);Reject("duplicate-entry",duplicate:true);
            Reject("parent-traversal",extra:"../outside.txt");Reject("nested-file",extra:"folder/inside.txt");Reject("absolute-path",extra:"/outside.txt");
            Reject("unknown-executable",extra:"anything.exe");Reject("backslash-path",extra:"..\\outside.txt");
            Reject("old-download",m=>m["created_utc"]=DateTimeOffset.UtcNow.AddHours(-25).ToString("O"));
            Reject("future-download",m=>m["created_utc"]=DateTimeOffset.UtcNow.AddMinutes(10).ToString("O"));
            Reject("non-utc-date",m=>m["created_utc"]="2026-01-01T10:00:00-05:00");
            Reject("unsupported-format",m=>m["format"]=2);Reject("wrong-native-format",m=>m["profile_format"]="json");
            Reject("unselected-session",m=>m["mode"]="either");Reject("invalid-title",m=>m["roast_title"]="different");
            Reject("missing-identity",m=>m["preparation_id"]="");Reject("bad-plan",m=>m["plan_id"]=0);
            Reject("nonfinite-weight",m=>m["green_oz"]="NaN");Reject("negative-weight",m=>m["green_oz"]="-1");
            Reject("unknown-roast",m=>m["roast_level"]="arbitrary");Reject("control-character",m=>m["coffee"]="bad\nname");
            Reject("off-target-mismatch",m=>m["off"]="440.2");Reject("manifest-alarm-mismatch",m=>{m["charge"]="351.0";});
            Reject("drop-before-charge",m=>m["drop"]="300.0");Reject("ceiling-exceeded",m=>{m["drop"]="600.0";m["off"]="600.1";});
            void Rewrite(ZipArchive z,string name,byte[] raw){z.GetEntry(name)?.Delete();using var stream=z.CreateEntry(name).Open();stream.Write(raw);}
            byte[] Bytes(ZipArchive z,string name){using var stream=z.GetEntry(name)!.Open();using var memory=new MemoryStream();stream.CopyTo(memory);return memory.ToArray();}
            void RejectModified(string name,Action<ZipArchive> edit)
            {
                string path=Make(name);using(var z=ZipFile.Open(path,ZipArchiveMode.Update))edit(z);
                bool refused=false;try{Preparation.Read(path,DateTimeOffset.UtcNow);}catch{refused=true;}
                if(!refused)throw new Exception("Did not reject "+name);checks.Add(name);
            }
            RejectModified("duplicate-json-fields",z=>Rewrite(z,"manifest.json",Encoding.UTF8.GetBytes(Encoding.UTF8.GetString(Bytes(z,"manifest.json")).Replace("\"format\":1,","\"format\":1,\"format\":1,"))));
            RejectModified("expanded-file-limit",z=>Rewrite(z,"reference.alog",new byte[Preparation.FileLimit+1]));
            RejectModified("forged-alarm-action-with-matching-checksum",z=>{
                var alarm=JsonNode.Parse(Bytes(z,"alarms.alrm"))!;alarm["alarmactions"]![0]=99;
                byte[] raw=JsonSerializer.SerializeToUtf8Bytes(alarm);Rewrite(z,"alarms.alrm",raw);
                var m=JsonNode.Parse(Bytes(z,"manifest.json"))!;m["files"]!["alarms.alrm"]=Convert.ToHexString(SHA256.HashData(raw)).ToLowerInvariant();Rewrite(z,"manifest.json",JsonSerializer.SerializeToUtf8Bytes(m));
            });
            bool networkRefused=false;try{Preparation.Read("\\\\invalid.example\\share\\preparation.zip",DateTimeOffset.UtcNow);}catch(InvalidDataException){networkRefused=true;}if(!networkRefused)throw new Exception("Network path accepted.");checks.Add("network-path-refused-before-opening");
            bool expired=false;try{valid.CheckAge(DateTimeOffset.UtcNow.AddHours(25));}catch(InvalidDataException){expired=true;}if(!expired)throw new Exception("Expired materialized package accepted.");checks.Add("age-rechecked-before-send");
            string encodedPath=Path.Combine(root,"a name # one.alog");File.WriteAllText(encodedPath,"fictional");
            string physicalPath=ArtisanTransport.ExistingLocalPath(encodedPath);
            if(!File.Exists(physicalPath) || File.ReadAllText(physicalPath)!="fictional" || physicalPath.StartsWith("\\\\"))throw new Exception("Physical preparation path differs.");
            checks.Add("physical-file-path-from-open-handle");
            string message=ArtisanTransport.FileMessage(encodedPath,true);
            if(!message.StartsWith("file:///") || !message.EndsWith("?template\n") || message.Contains(' ') || message.Contains('#'))throw new Exception("Unsafe file URL encoding.");checks.Add("file-url-encoding");
            foreach(var version in new[]{new Version(3,1,0),new Version(4,0,2),new Version(4,0,2,0)})
            {if(!ArtisanTransport.Supports(version))throw new Exception("Reviewed version rejected.");checks.Add("reviewed-version-"+version);}
            foreach(var version in new[]{new Version(3,1,1),new Version(4,0,0),new Version(4,0,3),new Version(4,2,0)})
            {if(ArtisanTransport.Supports(version))throw new Exception("Unreviewed version accepted.");checks.Add("unreviewed-version-"+version);}
            if(ArtisanTransport.Supports(null))throw new Exception("Missing version accepted.");checks.Add("missing-version-refused");
            // Exercise exact send bytes with a random test-only pipe. No real Artisan endpoint is opened.
            string testPipe="CremaPilotTest-"+Guid.NewGuid().ToString("N");
            using(var server=new NamedPipeServerStream(testPipe,PipeDirection.In,1,PipeTransmissionMode.Byte,PipeOptions.Asynchronous))
            using(var client=new NamedPipeClientStream(".",testPipe,PipeDirection.Out,PipeOptions.Asynchronous))
            {
                var accepted=server.WaitForConnectionAsync();client.Connect(2000);accepted.GetAwaiter().GetResult();
                using var reader=new StreamReader(server,new UTF8Encoding(false,true));
                var received=reader.ReadLineAsync();
                ArtisanTransport.Send(client,Path.Combine(extracted,"reference.alog"),true).GetAwaiter().GetResult();
                if(received.GetAwaiter().GetResult()!=ArtisanTransport.FileMessage(Path.Combine(extracted,"reference.alog"),true).TrimEnd('\n'))throw new Exception("Background message changed.");
                received=reader.ReadLineAsync();
                ArtisanTransport.Send(client,Path.Combine(extracted,"alarms.alrm"),false).GetAwaiter().GetResult();
                if(received.GetAwaiter().GetResult()!=ArtisanTransport.FileMessage(Path.Combine(extracted,"alarms.alrm"),false).TrimEnd('\n'))throw new Exception("Alarm message changed.");
            }
            checks.Add("background-and-alarm-messages-on-test-only-pipe");
            File.WriteAllText(reportPath,JsonSerializer.Serialize(new{result="passed",checks,count=checks.Count,fixtureDirectory=root,realArtisanTouched=false,serverChanged=false},new JsonSerializerOptions{WriteIndented=true}));return 0;
        }
        catch(Exception e){File.WriteAllText(reportPath,JsonSerializer.Serialize(new{result="failed",checks,error=e.ToString()}));return 1;}
    }
}
