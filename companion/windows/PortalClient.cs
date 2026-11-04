using System.Net;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text.Json;
using System.Runtime.InteropServices;

namespace CremaCompanion;

internal sealed record PortalCredential(string Origin,string Access,string Refresh);
internal sealed class PortalClient : IDisposable
{
    private readonly HttpClient http;
    private readonly SemaphoreSlim gate=new(1,1);
    internal Uri Origin {get;}
    private PortalCredential? credential;
    private readonly string credentialPath;
    internal bool Connected=>credential!=null;
    internal PortalClient(string origin,string stateRoot,HttpMessageHandler? testHandler=null)
    {
        Origin=ValidateOrigin(origin);
        http=new HttpClient(testHandler??new HttpClientHandler{AllowAutoRedirect=false,UseCookies=false}){BaseAddress=Origin,Timeout=TimeSpan.FromSeconds(20)};
        credentialPath=Path.Combine(stateRoot,"connection.dat");
    }
    internal static Uri ValidateOrigin(string value)
    {
        if(!Uri.TryCreate(value.Trim().TrimEnd('/')+"/",UriKind.Absolute,out var uri) || uri.Scheme!="https" || !string.IsNullOrEmpty(uri.UserInfo) || uri.AbsolutePath!="/" || !string.IsNullOrEmpty(uri.Query) || !string.IsNullOrEmpty(uri.Fragment))
            throw new InvalidDataException("Enter your Crema HTTPS address without a page path, for example https://crema.example.com.");
        return uri;
    }
    internal static PortalClient? Restore(string stateRoot)
    {
        string file=Path.Combine(stateRoot,"connection.dat");
        if(!File.Exists(file))return null;
        if(new FileInfo(file).Length>16384)throw new InvalidDataException("Saved connection is invalid. Connect again.");
        byte[] raw=WindowsSecret.Unprotect(File.ReadAllBytes(file));
        try
        {
            var saved=JsonSerializer.Deserialize<PortalCredential>(raw)??throw new InvalidDataException("Saved connection is empty.");
            var client=new PortalClient(saved.Origin,stateRoot);client.credential=saved;return client;
        }
        finally{System.Security.Cryptography.CryptographicOperations.ZeroMemory(raw);}
    }
    private async Task<JsonElement> Json(HttpRequestMessage request,CancellationToken ct)
    {
        using(request)
        using(var response=await http.SendAsync(request,HttpCompletionOption.ResponseHeadersRead,ct))
        {
            var raw=await Bounded(response,1_000_000,ct);
            JsonElement value;
            try{value=JsonDocument.Parse(raw,new JsonDocumentOptions{MaxDepth=24}).RootElement.Clone();}
            catch(JsonException){throw new IOException("This portal does not support connected Companion yet, or returned an invalid response.");}
            if(!response.IsSuccessStatusCode)throw new PortalException(response.StatusCode,value.TryGetProperty("error",out var e)?e.GetString()??"Portal request failed.":"Portal request failed.",value);
            return value;
        }
    }
    private static HttpRequestMessage Post(string path,object data)=>new(HttpMethod.Post,"api/companion/v1/"+path){Content=JsonContent.Create(data)};
    internal Task<JsonElement> Start(CancellationToken ct)=>Json(Post("start/",new{name=Environment.MachineName}),ct);
    internal async Task<bool> Poll(string code,CancellationToken ct)
    {
        var value=await Json(Post("token/",new{device_code=code}),ct);SaveTokens(value);return true;
    }
    private void SaveTokens(JsonElement value)
    {
        var next=new PortalCredential(Origin.AbsoluteUri,value.GetProperty("access_token").GetString()!,value.GetProperty("refresh_token").GetString()!);
        if(!System.Text.RegularExpressions.Regex.IsMatch(next.Access,"^[A-Za-z0-9_-]{43}$") || !System.Text.RegularExpressions.Regex.IsMatch(next.Refresh,"^[A-Za-z0-9_-]{43}$"))throw new InvalidDataException("Invalid portal credentials.");
        Directory.CreateDirectory(Path.GetDirectoryName(credentialPath)!);
        byte[] plain=JsonSerializer.SerializeToUtf8Bytes(next);
        try{File.WriteAllBytes(credentialPath+".tmp",WindowsSecret.Protect(plain));File.Move(credentialPath+".tmp",credentialPath,true);credential=next;}
        finally{System.Security.Cryptography.CryptographicOperations.ZeroMemory(plain);}
    }
    private async Task Refresh(CancellationToken ct)
    {
        if(credential==null)throw new IOException("Connect to Crema first.");
        var value=await Json(Post("token/",new{refresh_token=credential.Refresh}),ct);SaveTokens(value);
    }
    internal async Task<JsonElement> Get(string path,CancellationToken ct)
    {
        await gate.WaitAsync(ct);
        try
        {
            if(credential==null)throw new IOException("Connect to Crema first.");
            for(int i=0;;i++)
            {
                using var request=new HttpRequestMessage(HttpMethod.Get,"api/companion/v1/"+path);
                request.Headers.Authorization=new AuthenticationHeaderValue("Bearer",credential.Access);
                try{return await Json(request,ct);}catch(PortalException e)when(e.Status==HttpStatusCode.Unauthorized && i==0){await Refresh(ct);}
            }
        }
        finally{gate.Release();}
    }
    internal async Task<byte[]> Prepare(int row,object data,CancellationToken ct)
    {
        await gate.WaitAsync(ct);
        try
        {
            await Refresh(ct);
            using var request=Post($"roasts/{row}/prepare/",data);
            request.Headers.Authorization=new AuthenticationHeaderValue("Bearer",credential!.Access);
            using var response=await http.SendAsync(request,HttpCompletionOption.ResponseHeadersRead,ct);
            var raw=await Bounded(response,Preparation.ArchiveLimit,ct);
            if(!response.IsSuccessStatusCode)
            {
                string message="The load changed or is unavailable. Refresh the roast list.";
                try{message=JsonDocument.Parse(raw).RootElement.GetProperty("error").GetString()??message;}catch(JsonException){}
                throw new IOException(message);
            }
            if(response.Content.Headers.ContentType?.MediaType!="application/zip")throw new IOException("The portal did not return a preparation ZIP.");
            return raw;
        }
        finally{gate.Release();}
    }
    internal async Task Disconnect(CancellationToken ct)
    {
        if(credential==null)return;
        await Refresh(ct);
        var request=Post("disconnect/",new{});request.Headers.Authorization=new AuthenticationHeaderValue("Bearer",credential!.Access);
        await Json(request,ct);Forget();
    }
    internal void Forget(){credential=null;if(File.Exists(credentialPath))File.Delete(credentialPath);}
    internal static async Task<byte[]> Bounded(HttpResponseMessage response,int limit,CancellationToken ct)
    {
        if(response.Content.Headers.ContentLength>limit)throw new IOException("Portal response is too large.");
        using var input=await response.Content.ReadAsStreamAsync(ct);using var output=new MemoryStream();byte[] buffer=new byte[8192];int read;
        while((read=await input.ReadAsync(buffer,ct))>0){if(output.Length+read>limit)throw new IOException("Portal response is too large.");output.Write(buffer,0,read);}return output.ToArray();
    }
    public void Dispose(){http.Dispose();gate.Dispose();}
}
internal sealed class PortalException(HttpStatusCode status,string message,JsonElement body):IOException(message)
{internal HttpStatusCode Status=>status;internal JsonElement Body=>body;}

internal static class WindowsSecret
{
    [StructLayout(LayoutKind.Sequential)]private struct Blob{internal int Length;internal IntPtr Data;}
    [DllImport("crypt32.dll",SetLastError=true,CharSet=CharSet.Unicode)]private static extern bool CryptProtectData(ref Blob data,string description,IntPtr entropy,IntPtr reserved,IntPtr prompt,int flags,out Blob output);
    [DllImport("crypt32.dll",SetLastError=true,CharSet=CharSet.Unicode)]private static extern bool CryptUnprotectData(ref Blob data,IntPtr description,IntPtr entropy,IntPtr reserved,IntPtr prompt,int flags,out Blob output);
    [DllImport("kernel32.dll")]private static extern IntPtr LocalFree(IntPtr value);
    internal static byte[] Protect(byte[] raw)=>Transform(raw,true);
    internal static byte[] Unprotect(byte[] raw)=>Transform(raw,false);
    private static byte[] Transform(byte[] raw,bool protect)
    {
        var input=new Blob{Length=raw.Length,Data=Marshal.AllocHGlobal(raw.Length)};Blob output=default;
        try
        {
            Marshal.Copy(raw,0,input.Data,raw.Length);
            bool ok=protect?CryptProtectData(ref input,"Crema Companion",IntPtr.Zero,IntPtr.Zero,IntPtr.Zero,1,out output):CryptUnprotectData(ref input,IntPtr.Zero,IntPtr.Zero,IntPtr.Zero,IntPtr.Zero,1,out output);
            if(!ok)throw new IOException("Windows could not unlock the saved connection. Sign in again on this Windows account.");
            var result=new byte[output.Length];Marshal.Copy(output.Data,result,0,result.Length);return result;
        }
        finally{for(int i=0;i<input.Length;i++)Marshal.WriteByte(input.Data,i,0);Marshal.FreeHGlobal(input.Data);if(output.Data!=IntPtr.Zero){for(int i=0;i<output.Length;i++)Marshal.WriteByte(output.Data,i,0);LocalFree(output.Data);}}
    }
}
