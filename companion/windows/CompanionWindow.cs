using System.Diagnostics;
using System.Globalization;
using System.Reflection;
using System.Text.Json;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

namespace CremaCompanion;

internal sealed class CompanionWindow : Form
{
    internal const string AppOrigin="https://companion.crema.invalid/";
    private readonly WebView2 web=new(){Dock=DockStyle.Fill};
    private readonly string root=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"CremaCompanionPilot");
    private readonly CancellationTokenSource lifetime=new();
    private PortalClient? portal;
    private JsonElement? account,roasts;
    private Preparation? preparation;
    private string? folder;
    private HandoffProgress progress=new();
    private bool busy,onlinePreparation,ready,curve,alarms;
    private bool initialized;
    private string artisan="",status="Connect to your roastery, or open a fresh preparation ZIP.",code="",verification="";
    private bool problem;
    private CancellationTokenSource? pairing;
    internal CompanionWindow(string? initialPath)
    {
        Text="Crema Companion";ClientSize=new Size(1000,825);MinimumSize=new Size(720,650);StartPosition=FormStartPosition.CenterScreen;BackColor=Color.FromArgb(244,247,244);
        Controls.Add(web);
        Shown+=async(_,_)=>await Initialize(initialPath);
        FormClosed+=(_,_)=>{pairing?.Cancel();lifetime.Cancel();web.Dispose();};
    }
    private async Task Initialize(string? path)
    {
        try
        {
            Directory.CreateDirectory(root);
            var environment=await CoreWebView2Environment.CreateAsync(null,Path.Combine(root,"webview"));
            await web.EnsureCoreWebView2Async(environment);
            var core=web.CoreWebView2;core.Settings.AreDevToolsEnabled=false;core.Settings.AreDefaultContextMenusEnabled=false;core.Settings.IsStatusBarEnabled=false;core.Settings.AreHostObjectsAllowed=false;core.Settings.IsGeneralAutofillEnabled=false;core.Settings.IsPasswordAutosaveEnabled=false;
            core.NavigationStarting+=(_,e)=>{if(e.Uri!=AppOrigin+"index.html")e.Cancel=true;};
            core.NewWindowRequested+=(_,e)=>e.Handled=true;
            core.DownloadStarting+=(_,e)=>e.Cancel=true;
            core.PermissionRequested+=(_,e)=>e.State=CoreWebView2PermissionState.Deny;
            core.AddWebResourceRequestedFilter("*",CoreWebView2WebResourceContext.All);
            core.WebResourceRequested+=(_,e)=>
            {
                var uri=new Uri(e.Request.Uri);string name=uri.AbsolutePath.TrimStart('/');
                bool allowed=uri.GetLeftPart(UriPartial.Authority)+"/"==AppOrigin && (name is "index.html" or "app.css" or "app.js");
                Stream? data=allowed?Assembly.GetExecutingAssembly().GetManifestResourceStream("CremaCompanion.ui."+name):null;
                string type=name.EndsWith(".js")?"text/javascript":name.EndsWith(".css")?"text/css":"text/html";
                e.Response=core.Environment.CreateWebResourceResponse(data??new MemoryStream(),data==null?404:200,data==null?"Not found":"OK",$"Content-Type: {type}; charset=utf-8\r\nCache-Control: no-store\r\nContent-Security-Policy: default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'none'; base-uri 'none'; form-action 'none'; frame-src 'none'\r\nX-Content-Type-Options: nosniff");
            };
            core.WebMessageReceived+=async(_,e)=>
            {
                if(e.Source!=AppOrigin+"index.html" || e.WebMessageAsJson.Length>4096)return;
                try{using var json=JsonDocument.Parse(e.WebMessageAsJson);await HandleAction(json.RootElement.Clone());}
                catch(Exception ex){SetStatus(ex is OperationCanceledException?"Connection cancelled.":ex.Message,true);}
            };
            core.NavigationCompleted+=async(_,e)=>
            {
                if(!e.IsSuccess)return;initialized=true;
                try
                {
                    string settings=Path.Combine(root,"settings.json");
                    if(File.Exists(settings) && new FileInfo(settings).Length<8192)artisan=JsonDocument.Parse(File.ReadAllText(settings)).RootElement.GetProperty("artisan").GetString()??"";
                    artisan=File.Exists(artisan)?artisan:ArtisanTransport.FindInstalled()??"";
                    portal=PortalClient.Restore(root);Publish();
                    if(path!=null)Read(path,false);
                    if(portal!=null)await RefreshPortal();
                }
                catch(Exception ex){SetStatus(ex.Message,true);}
            };
            core.Navigate(AppOrigin+"index.html");
        }
        catch(Exception)
        {
            Controls.Remove(web);
            var panel=new FlowLayoutPanel{Dock=DockStyle.Fill,Padding=new Padding(30),FlowDirection=FlowDirection.TopDown};
            panel.Controls.Add(new Label{AutoSize=true,MaximumSize=new Size(600,0),Text="The redesigned Companion needs Microsoft Edge WebView2 Runtime. Install the Microsoft runtime, then reopen Companion. The classic offline preparation window is available meanwhile."});
            var download=new Button{AutoSize=true,Text="Open Microsoft runtime download"};download.Click+=(_,_)=>OpenBrowser("https://developer.microsoft.com/en-us/microsoft-edge/webview2/");panel.Controls.Add(download);
            var classic=new Button{AutoSize=true,Text="Open classic offline window"};classic.Click+=(_,_)=>{using var fallback=new ClassicCompanionWindow(path);Hide();fallback.ShowDialog();Close();};panel.Controls.Add(classic);Controls.Add(panel);
        }
    }
    private async Task HandleAction(JsonElement data)
    {
        string action=data.GetProperty("action").GetString()??"";
        if(action=="hello"){Publish();return;}
        if(action=="cancel"){pairing?.Cancel();return;}
        if(busy)return;
        if(action=="check")
        {
            string field=data.GetProperty("field").GetString()??"";bool value=data.GetProperty("value").GetBoolean();
            if(field=="ready" && progress.Stage==HandoffStage.Review)ready=value;
            if(field=="curve" && progress.Stage==HandoffStage.BackgroundSent)curve=value;
            if(field=="alarms" && progress.Stage==HandoffStage.AlarmsSent)alarms=value;Publish();return;
        }
        busy=true;Publish();
        try
        {
            switch(action)
            {
                case "connect":await Connect(data.GetProperty("origin").GetString()??"");break;
                case "refresh":await RefreshPortal();break;
                case "disconnect":
                    if(portal!=null)await portal.Disconnect(lifetime.Token);
                    portal?.Dispose();portal=null;account=null;roasts=null;Clear();SetStatus("Disconnected. Your portal can also revoke this computer.");break;
                case "forget":
                    portal?.Forget();portal?.Dispose();portal=null;account=null;roasts=null;Clear();SetStatus("Saved sign-in removed from this PC. Revoke the computer in Crema if it could not connect.");break;
                case "manage":if(portal!=null)OpenBrowser(new Uri(portal.Origin,"companion/").AbsoluteUri);break;
                case "open":using(var dialog=new OpenFileDialog{Filter="Crema preparation (*.zip;*.crema)|*.zip;*.crema",CheckFileExists=true})if(dialog.ShowDialog(this)==DialogResult.OK)Read(dialog.FileName,false);break;
                case "choose":ChooseArtisan();break;
                case "prepare":await Prepare(data);break;
                case "copy":if(preparation!=null){Clipboard.SetText(preparation.Title);SetStatus("Title copied. Paste it into Artisan Properties.");}break;
                case "next":await Next();break;
                case "clear":Clear();SetStatus("Choose your next roast.");break;
            }
        }
        catch(Exception ex){SetStatus(ex is OperationCanceledException?"Connection cancelled.":ex.Message,true);}
        finally{busy=false;Publish();}
    }
    private async Task Connect(string origin)
    {
        if(portal?.Connected==true)throw new IOException("Disconnect the current roastery before connecting another.");
        pairing?.Cancel();pairing=new CancellationTokenSource(TimeSpan.FromMinutes(10));using var linked=CancellationTokenSource.CreateLinkedTokenSource(pairing.Token,lifetime.Token);
        portal?.Dispose();portal=new PortalClient(origin,root);Clear();account=null;roasts=null;
        var start=await portal.Start(linked.Token);code=start.GetProperty("user_code").GetString()!;
        verification=start.GetProperty("verification_uri").GetString()!;
        if(new Uri(verification)!=new Uri(portal.Origin,"companion/"))throw new IOException("The portal returned an unexpected sign-in address.");
        SetStatus("Sign in in your browser. Enter the displayed code and approve this computer.");OpenBrowser(verification);
        int interval=Math.Clamp(start.GetProperty("interval").GetInt32(),5,60);
        try
        {
            while(true)
            {
                await Task.Delay(TimeSpan.FromSeconds(interval),linked.Token);
                try{if(await portal.Poll(start.GetProperty("device_code").GetString()!,linked.Token))break;}
                catch(PortalException ex)when(ex.Message=="authorization_pending"){}
                catch(PortalException ex)when(ex.Message=="slow_down"){interval=Math.Min(60,interval+5);}
            }
            await RefreshPortal();SetStatus("Connected. Choose a roast from your accepted plans.");
        }
        finally{code="";verification="";Publish();}
    }
    private async Task RefreshPortal()
    {
        if(portal?.Connected!=true)throw new IOException("Connect to your Crema portal first.");
        account=await portal.Get("me/",lifetime.Token);roasts=(await portal.Get("roasts/",lifetime.Token)).GetProperty("roasts");SetStatus("Roast list and account theme refreshed.");
    }
    private async Task Prepare(JsonElement data)
    {
        if(portal?.Connected!=true || roasts==null)throw new IOException("Connect and refresh first.");
        int row=data.GetProperty("row").GetInt32(),profile=data.GetProperty("profile").GetInt32();string mode=data.GetProperty("mode").GetString()??"";
        if(mode is not ("first" or "second") || !data.GetProperty("confirmed").GetBoolean())throw new IOException("Review and confirm this load first.");
        var selected=roasts.Value.EnumerateArray().FirstOrDefault(x=>x.GetProperty("id").GetInt32()==row);
        if(selected.ValueKind!=JsonValueKind.Object)throw new IOException("Refresh the roast list first.");
        Clear();
        byte[] raw=await portal.Prepare(row,new{mode,profile,confirmed=true,fingerprint=selected.GetProperty("fingerprint").GetString()},lifetime.Token);
        string downloads=Path.Combine(root,"downloads");Directory.CreateDirectory(downloads);string file=Path.Combine(downloads,Guid.NewGuid()+".zip");File.WriteAllBytes(file,raw);Read(file,true);
    }
    private void Clear(){preparation=null;folder=null;onlinePreparation=false;progress=new();ready=curve=alarms=false;}
    private void Read(string path,bool online)
    {
        Clear();
        try{var value=Preparation.Read(path,DateTimeOffset.UtcNow);folder=value.Materialize(root);preparation=value;onlinePreparation=online;SetStatus(online?"Current preparation received. Check Artisan is idle before loading.":"Offline preparation. Compare it with the current portal plan before loading.");}
        catch{Publish();throw;}
    }
    private void ChooseArtisan()
    {
        using var dialog=new OpenFileDialog{Title="Choose installed artisan.exe",Filter="Artisan (artisan.exe)|artisan.exe",CheckFileExists=true};
        if(dialog.ShowDialog(this)!=DialogResult.OK)return;
        ArtisanTransport.InspectExecutable(dialog.FileName);artisan=dialog.FileName;Directory.CreateDirectory(root);File.WriteAllText(Path.Combine(root,"settings.json"),JsonSerializer.Serialize(new{artisan}));SetStatus("Artisan location remembered.");
    }
    private async Task Next()
    {
        if(preparation==null || folder==null)throw new IOException("Choose a preparation first.");
        if(progress.Stage is HandoffStage.Verified or HandoffStage.Uncertain){Clear();SetStatus("Choose a fresh preparation.");return;}
        preparation.CheckAge(DateTimeOffset.UtcNow);
        // Live check before BOTH file sends and final operator verification.
        if(onlinePreparation)
        {
            if(portal?.Connected!=true)throw new IOException("Reconnect and refresh before loading this preparation.");
            await portal.Get($"preparations/{Guid.Parse(preparation.Id)}/validate/",lifetime.Token);
        }
        if(progress.Stage==HandoffStage.AlarmsSent){progress.Verify(alarms);SetStatus("Verified by you. Start and operate the roast in Artisan.");return;}
        if(!progress.CanSend(ready,curve))throw new IOException("Complete the current check first.");
        bool attempted=false;
        try
        {
            using var pipe=await ArtisanTransport.ConnectMain();
            if(pipe==null)
            {
                if(ArtisanTransport.IsRunning())throw new IOException("Artisan is open but its main connection is unavailable. Finish startup dialogs and retry as the same Windows user.");
                if(progress.Stage!=HandoffStage.Review)throw new IOException("Artisan closed. Open a fresh preparation.");
                if(!File.Exists(artisan)){ChooseArtisan();if(!File.Exists(artisan))return;}
                ArtisanTransport.Start(artisan);ready=false;SetStatus("Artisan is opening. Finish startup, check monitoring OFF and confirm readiness again.");return;
            }
            bool background=progress.Stage==HandoffStage.Review;string file=background?"reference.alog":"alarms.alrm";
            if(!File.ReadAllBytes(Path.Combine(folder,file)).SequenceEqual(preparation.Data[file]))throw new IOException("The local preparation changed. Open a fresh preparation.");
            attempted=true;await ArtisanTransport.Send(pipe,Path.Combine(folder,file),background);
            progress.Sent(background,ready,curve);SetStatus(background?"Background sent. Check the curve in Artisan.":"Alarms sent. Compare Charge, Drop and Off in Artisan.");
        }
        catch{if(attempted)progress.Uncertain();throw;}
    }
    private void SetStatus(string message,bool error=false){status=message;problem=error;Publish();}
    private void Publish()
    {
        if(!initialized || IsDisposed)return;
        var p=preparation;string version="Artisan not selected";
        try{if(File.Exists(artisan))version="Artisan "+ArtisanTransport.InspectExecutable(artisan).ToString(3);}catch{version="Choose a supported Artisan installation";}
        web.CoreWebView2.PostWebMessageAsJson(JsonSerializer.Serialize(new{busy,status,problem,code,verification,connected=portal?.Connected==true,origin=portal?.Origin.GetLeftPart(UriPartial.Authority)??"",account,roasts,stage=progress.Stage.ToString(),ready,curve,alarms,artisan=version,onlinePreparation,preparation=p==null?null:new{p.Coffee,p.Roast,p.Roaster,p.Green,p.Mode,p.Title,p.Charge,p.Drop,p.Off,p.Plan,p.Row}}));
    }
    private static void OpenBrowser(string uri)=>Process.Start(new ProcessStartInfo(uri){UseShellExecute=true});
}
