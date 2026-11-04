using System.Net;
using System.Net.Http.Json;
using System.Reflection;
using System.Text;
using System.Text.Json;

namespace CremaCompanion;
internal static class ConnectedChecks
{
    private sealed class FakeHandler:HttpMessageHandler
    {
        internal readonly Queue<Func<HttpRequestMessage,HttpResponseMessage>> Responses=new();
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request,CancellationToken cancellationToken)
        {
            if(request.RequestUri?.Host!="roastery.example")throw new Exception("Unexpected host in isolated HTTP fixture.");
            if(Responses.Count==0)throw new Exception("Unexpected HTTP request.");
            return Task.FromResult(Responses.Dequeue()(request));
        }
    }
    private static HttpResponseMessage Response(object data,HttpStatusCode status=HttpStatusCode.OK)=>new(status){Content=JsonContent.Create(data)};
    internal static void Run(List<string> checks,string fixtureRoot)=>RunAsync(checks,fixtureRoot).GetAwaiter().GetResult();
    private static async Task RunAsync(List<string> checks,string fixtureRoot)
    {
        foreach(string bad in new[]{"http://roastery.example","https://user:secret@roastery.example","https://roastery.example/path","https://roastery.example/?token=x","https://roastery.example/#x","file:///C:/test","javascript:alert(1)","https://roastery.example/../secret"})
        {try{PortalClient.ValidateOrigin(bad);throw new Exception("Unsafe portal origin accepted: "+bad);}catch(InvalidDataException){}}
        checks.Add("https-origin-only-no-path-query-credentials");
        if(PortalClient.ValidateOrigin("https://roastery.example").AbsoluteUri!="https://roastery.example/")throw new Exception("Origin normalization failed.");
        checks.Add("portal-origin-normalization");
        byte[] plain=Encoding.UTF8.GetBytes("fictional-token-never-a-real-account"),encrypted=WindowsSecret.Protect(plain);
        if(encrypted.SequenceEqual(plain) || !WindowsSecret.Unprotect(encrypted).SequenceEqual(plain))throw new Exception("Windows credential protection failed.");
        checks.Add("windows-current-user-protection-roundtrip");
        encrypted[encrypted.Length/2]^=1;
        try{WindowsSecret.Unprotect(encrypted);throw new Exception("Corrupt credential accepted.");}catch(IOException){}
        checks.Add("corrupt-protected-credential-rejected");
        var handler=new FakeHandler();using var client=new PortalClient("https://roastery.example",fixtureRoot,handler);
        handler.Responses.Enqueue(r=>{if(r.Method!=HttpMethod.Post || r.RequestUri!.AbsolutePath!="/api/companion/v1/start/" || r.Headers.Authorization!=null)throw new Exception("Incorrect pairing request.");return Response(new{user_code="ABCD-EFGH",device_code="fictional",verification_uri="https://roastery.example/companion/",interval=5,expires_in=600});});
        var start=await client.Start(CancellationToken.None);if(start.GetProperty("user_code").GetString()!="ABCD-EFGH")throw new Exception("Pairing response failed.");
        checks.Add("native-device-pairing-request");
        handler.Responses.Enqueue(_=>Response(new{error="authorization_pending"},HttpStatusCode.BadRequest));
        try{await client.Poll("fictional",CancellationToken.None);throw new Exception("Pending response accepted.");}catch(PortalException e)when(e.Message=="authorization_pending"){}
        checks.Add("pending-device-code-not-signed-in");
        string a=new('A',43),b=new('B',43),c=new('C',43),d=new('D',43);
        handler.Responses.Enqueue(_=>Response(new{access_token=a,refresh_token=b}));await client.Poll("fictional",CancellationToken.None);
        var file=Path.Combine(fixtureRoot,"connection.dat");
        if(!client.Connected || Encoding.UTF8.GetString(File.ReadAllBytes(file)).Contains(a))throw new Exception("Tokens were not protected.");
        checks.Add("saved-token-file-contains-no-plaintext-secret");
        using(var restored=PortalClient.Restore(fixtureRoot))if(restored?.Origin.AbsoluteUri!="https://roastery.example/" || !restored.Connected)throw new Exception("Connection could not be restored.");
        checks.Add("saved-connection-bound-to-original-origin");
        handler.Responses.Enqueue(r=>{if(r.Headers.Authorization?.Parameter!=a)throw new Exception("Wrong bearer credential.");return Response(new{error="expired"},HttpStatusCode.Unauthorized);});
        handler.Responses.Enqueue(r=>{if(r.RequestUri!.AbsolutePath!="/api/companion/v1/token/" || !r.Content!.ReadAsStringAsync().GetAwaiter().GetResult().Contains(b))throw new Exception("Wrong refresh request.");return Response(new{access_token=c,refresh_token=d});});
        handler.Responses.Enqueue(r=>{if(r.Headers.Authorization?.Parameter!=c)throw new Exception("Old token was reused.");return Response(new{username="fictional"});});
        if((await client.Get("me/",CancellationToken.None)).GetProperty("username").GetString()!="fictional")throw new Exception("Refresh/retry failed.");
        checks.Add("one-refresh-retry-uses-rotated-token");
        handler.Responses.Enqueue(_=>Response(new{access_token=c,refresh_token=d}));
        handler.Responses.Enqueue(r=>{if(r.RequestUri!.AbsolutePath!="/api/companion/v1/roasts/7/prepare/" || r.Headers.Authorization?.Parameter!=c)throw new Exception("Wrong preparation request.");return new(HttpStatusCode.OK){Content=new ByteArrayContent([80,75]){Headers={ContentType=new("application/zip")}}};});
        if(!(await client.Prepare(7,new{confirmed=true},CancellationToken.None)).SequenceEqual(new byte[]{80,75}))throw new Exception("Preparation download failed.");
        checks.Add("authenticated-bounded-preparation-download");
        handler.Responses.Enqueue(_=>Response(new{error="stale load"},HttpStatusCode.Conflict));
        try{await client.Get("preparations/fictional/validate/",CancellationToken.None);throw new Exception("Stale load accepted.");}catch(PortalException e)when(e.Status==HttpStatusCode.Conflict){}
        checks.Add("stale-preparation-blocks-handoff-validation");
        using(var oversized=new HttpResponseMessage(HttpStatusCode.OK){Content=new ByteArrayContent(new byte[16])})
        {try{await PortalClient.Bounded(oversized,8,CancellationToken.None);throw new Exception("Oversized response accepted.");}catch(IOException){}}
        checks.Add("bounded-native-http-response");
        handler.Responses.Enqueue(_=>new(HttpStatusCode.Found){Content=new StringContent("unexpected login redirect")});
        try{await client.Get("me/",CancellationToken.None);throw new Exception("Redirect was accepted.");}catch(IOException){}
        checks.Add("login-redirect-is-not-an-api-response");
        handler.Responses.Enqueue(_=>Response(new{access_token=c,refresh_token=d}));handler.Responses.Enqueue(_=>Response(new{disconnected=true}));await client.Disconnect(CancellationToken.None);
        if(client.Connected || File.Exists(file) || handler.Responses.Count!=0)throw new Exception("Disconnect did not clear credentials.");
        checks.Add("disconnect-revokes-and-forgets-local-credential");
        var assembly=Assembly.GetExecutingAssembly();
        foreach(var name in new[]{"index.html","app.css","app.js"})if(assembly.GetManifestResourceStream("CremaCompanion.ui."+name)==null)throw new Exception("Missing embedded interface asset.");
        checks.Add("interface-assets-bundled-offline");
    }
}
