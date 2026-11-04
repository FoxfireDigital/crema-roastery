using System.Globalization;
using System.Text.Json;

namespace CremaCompanion;

internal sealed class CompanionWindow : Form
{
    private static readonly Color Ink=Color.FromArgb(30,58,47), Muted=Color.FromArgb(88,105,96), Cream=Color.FromArgb(245,243,237), Green=Color.FromArgb(34,79,59);
    private readonly string stateRoot=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"CremaCompanionPilot");
    private readonly Button open=Button("Open preparation"), choose=Button("Choose Artisan"), load=Button("Load background"), copy=Button("Copy title"), help=Button("Help && settings");
    private readonly TextBox zipPath=new(){Dock=DockStyle.Fill,PlaceholderText="Paste a local preparation ZIP path and press Enter",AccessibleName="Preparation ZIP path"};
    private readonly Label coffee=TextLabel("Your next roast starts here",22,true), roast=TextLabel("Open or drop a fresh preparation ZIP from Crema.",10), local=TextLabel("No preparation open",9), artisanStatus=TextLabel("Finding Artisan…",9);
    private readonly Label machine=TextLabel("—",14,true), weight=TextLabel("—",14,true), schedule=TextLabel("—",14,true), title=TextLabel("Roast title appears here",10,true);
    private readonly Label charge=TextLabel("—",24,true), drop=TextLabel("—",24,true), off=TextLabel("—",24,true);
    private readonly Label status=TextLabel("Open your preparation to begin.",11,true), instruction=TextLabel("Compare this load with the current plan before sending it to Artisan.",10);
    private readonly Label[] steps=Enumerable.Range(0,4).Select(_=>TextLabel("",9,true)).ToArray();
    private readonly CheckBox ready=new(){AutoSize=true,Text="Load and USB roaster checked; previous work saved; Artisan idle, monitoring OFF.",AccessibleName="Readiness: load checked and Artisan idle"};
    private readonly CheckBox curve=new(){AutoSize=true,Text="The expected background is visible in Artisan; monitoring is still OFF.",AccessibleName="Confirm background visible and Artisan idle"};
    private readonly CheckBox alarms=new(){AutoSize=true,Text="I checked Charge, Drop and Off targets in Artisan; monitoring is still OFF.",AccessibleName="Confirm alarm targets and Artisan idle"};
    private readonly TableLayoutPanel helpPanel,readyRow,curveRow,alarmsRow;
    private HandoffProgress progress=new();
    private Preparation? preparation;
    private string? folder;
    private string artisan="";
    private bool busy;
    internal CompanionWindow(string? initialPath)
    {
        Text="Crema Companion — Pilot";Name="CremaCompanionPilot";
        Font=new Font("Segoe UI",10);AutoScaleMode=AutoScaleMode.Dpi;
        ClientSize=new Size(800,775);MinimumSize=new Size(650,700);StartPosition=FormStartPosition.CenterScreen;
        BackColor=Cream;ForeColor=Ink;AllowDrop=true;
        var layout=Column(20);layout.Dock=DockStyle.Fill;layout.AutoSize=false;layout.AutoScroll=true;Controls.Add(layout);
        var header=Grid(2);header.ColumnStyles.Clear();header.ColumnStyles.Add(new ColumnStyle(SizeType.Percent,100));header.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
        var brand=Column(0);Add(brand,TextLabel("Crema Companion",21,true));Add(brand,TextLabel("Prepare your next roast in Artisan",10));header.Controls.Add(brand,0,0);header.Controls.Add(help,1,0);Add(layout,header);
        var strip=Grid(4);strip.Margin=new Padding(0,8,0,14);
        foreach(var step in steps){step.AutoSize=false;step.Dock=DockStyle.Fill;step.Height=36;step.TextAlign=ContentAlignment.MiddleCenter;step.Margin=new Padding(0,0,5,0);strip.Controls.Add(step);}Add(layout,strip);
        var files=Grid(2);files.ColumnStyles.Clear();files.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));files.ColumnStyles.Add(new ColumnStyle(SizeType.Percent,100));files.Controls.Add(open,0,0);local.Anchor=AnchorStyles.Left;local.Margin=new Padding(12,0,0,0);files.Controls.Add(local,1,0);Add(layout,files);
        var roastCard=Card();Add(roastCard,coffee);Add(roastCard,roast);
        var fields=Grid(3);fields.Margin=new Padding(0,10,0,0);fields.Controls.Add(Field("ROASTER",machine),0,0);fields.Controls.Add(Field("GREEN WEIGHT",weight),1,0);fields.Controls.Add(Field("SCHEDULE",schedule),2,0);Add(roastCard,fields);Add(layout,roastCard);
        var targets=Grid(3);targets.Margin=new Padding(0,0,0,10);
        targets.Controls.Add(Target("CHARGE",charge),0,0);targets.Controls.Add(Target("DROP",drop),1,0);targets.Controls.Add(Target("OFF",off),2,0);Add(layout,targets);
        var titleRow=Grid(2);titleRow.ColumnStyles.Clear();titleRow.ColumnStyles.Add(new ColumnStyle(SizeType.Percent,100));titleRow.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
        titleRow.Controls.Add(Field("ROAST TITLE · paste into Artisan Properties",title),0,0);titleRow.Controls.Add(copy,1,0);Add(layout,titleRow);
        var actionCard=Card();Add(actionCard,artisanStatus);Add(actionCard,status);Add(actionCard,instruction);
        readyRow=CheckRow(ready);curveRow=CheckRow(curve);alarmsRow=CheckRow(alarms);Add(actionCard,readyRow);Add(actionCard,curveRow);Add(actionCard,alarmsRow);
        load.AutoSize=false;load.Dock=DockStyle.Top;load.Height=46;load.MinimumSize=new Size(230,46);load.MaximumSize=new Size(0,46);load.Margin=new Padding(0,9,0,0);Add(actionCard,load);Add(layout,actionCard);
        Add(layout,TextLabel("Preparation only · Start and operate the roast in Artisan",9));
        helpPanel=Card();helpPanel.Visible=false;
        Add(helpPanel,TextLabel("Help && settings",12,true));Add(helpPanel,choose);Add(helpPanel,zipPath);
        Add(helpPanel,TextLabel("Use a fresh ZIP from your own Crema portal. Changed plans need a new download. This offline pilot cannot detect live edits, the USB machine, heat or an active roast.",9));
        Add(helpPanel,TextLabel("After the background appears, inspect Config → Alarms. Artisan 4 Production mode hides Alarms: use Config → Mode → Standard to inspect it. Return to Production afterward if desired.",9));
        Add(helpPanel,TextLabel("Copy title replaces clipboard text. Paste it into Roast → Properties → Title. Capture photo and Upload .alog stay under the batch in Crema.",9));
        Add(helpPanel,TextLabel("Sent means a request was delivered, not that Artisan loaded it. Off stops Artisan monitoring; it does not guarantee a heater shutdown. File → New starts monitoring/recording: use RESET, not New, to clear disposable test work while idle.",9));
        Add(helpPanel,TextLabel("Private pilot · Artisan 3.1.0 / 4.0.2 · No service or administrator account required",9));Add(layout,helpPanel);
        var tips=new ToolTip();tips.SetToolTip(local,"The preparation is checked locally. Re-download after changes to the live plan.");tips.SetToolTip(copy,"Replaces clipboard text; paste into Artisan’s active roast Title.");tips.SetToolTip(off,"Artisan monitoring OFF, not a guaranteed physical heater shutdown.");
        open.Click+=(_,_)=>OpenPreparation();choose.Click+=(_,_)=>ChooseArtisan();help.Click+=(_,_)=>{helpPanel.Visible=!helpPanel.Visible;help.Text=helpPanel.Visible?"Hide help":"Help && settings"; help.AccessibleName=help.Text.Replace("&&","&"); Wrap(layout,Math.Max(420,layout.ClientSize.Width-65)); layout.PerformLayout();};
        zipPath.KeyDown+=(_,e)=>{if(e.KeyCode==Keys.Enter && !busy){e.SuppressKeyPress=true;Read(zipPath.Text.Trim().Trim('"'));}};
        load.Click+=async (_,_)=>await Next();
        foreach(var check in new[]{ready,curve,alarms})check.CheckedChanged+=(_,_)=>UpdateControls();
        copy.Click+=(_,_)=>{try{if(preparation!=null){Clipboard.SetText(preparation.Title);SetStatus("Title copied — paste into Artisan Properties.");}}catch(Exception e){SetStatus("Clipboard unavailable: "+e.Message,true);}};
        DragEnter+=(_,e)=>{if(!busy && e.Data?.GetData(DataFormats.FileDrop) is string[] paths && paths.Length==1)e.Effect=DragDropEffects.Copy;};
        DragDrop+=(_,e)=>{if(!busy && e.Data?.GetData(DataFormats.FileDrop) is string[] paths && paths.Length==1)Read(paths[0]);};
        layout.SizeChanged+=(_,_)=>{int width=Math.Max(420,layout.ClientSize.Width-65);Wrap(layout,width);};
        LoadSettings();RefreshArtisanStatus();UpdateControls();Shown+=(_,_)=>{if(initialPath!=null)Read(initialPath);};
    }
    private static Label TextLabel(string text,int size=10,bool bold=false)=>new(){AutoSize=true,MaximumSize=new Size(600,0),Text=text,ForeColor=size<=10?Muted:Ink,Margin=new Padding(0,0,0,5),Font=new Font("Segoe UI",size,bold?FontStyle.Bold:FontStyle.Regular)};
    private static Button Button(string text)=>new(){AutoSize=true,Text=text,AccessibleName=text.Replace("&&","&"),Padding=new Padding(11,7,11,7),FlatStyle=FlatStyle.Flat,BackColor=Color.White,ForeColor=Ink,Margin=new Padding(0,0,0,6)};
    private static TableLayoutPanel Column(int padding){var column=new TableLayoutPanel{AutoSize=true,AutoSizeMode=AutoSizeMode.GrowAndShrink,ColumnCount=1,Padding=new Padding(padding),Dock=DockStyle.Top,Margin=Padding.Empty};column.ColumnStyles.Add(new ColumnStyle(SizeType.Percent,100));return column;}
    private static TableLayoutPanel Grid(int columns){var grid=new TableLayoutPanel{AutoSize=true,ColumnCount=columns,Dock=DockStyle.Top,Margin=new Padding(0,0,0,8)};for(int i=0;i<columns;i++)grid.ColumnStyles.Add(new ColumnStyle(SizeType.Percent,100f/columns));return grid;}
    private static TableLayoutPanel Card(){var card=Column(16);card.BackColor=Color.White;card.Margin=new Padding(0,0,0,12);return card;}
    private static void Add(TableLayoutPanel layout,Control control){int row=layout.RowCount++;layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));layout.Controls.Add(control,0,row);}
    private static TableLayoutPanel Field(string caption,Label value){var field=Column(0);Add(field,TextLabel(caption,8,true));Add(field,value);return field;}
    private static TableLayoutPanel Target(string caption,Label value){var card=Card();card.BackColor=Color.FromArgb(231,238,231);card.Margin=new Padding(0,0,7,0);Add(card,TextLabel(caption+" · BT °F",9,true));Add(card,value);return card;}
    private static TableLayoutPanel CheckRow(CheckBox check)
    {
        var text=TextLabel(check.Text,10);check.Text="";check.Margin=new Padding(0,3,9,0);
        var row=Grid(2);row.ColumnStyles.Clear();row.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));row.ColumnStyles.Add(new ColumnStyle(SizeType.Percent,100));
        row.Tag=check;row.Controls.Add(check,0,0);row.Controls.Add(text,1,0);
        row.SizeChanged+=(_,_)=>text.MaximumSize=new Size(Math.Max(100,row.ClientSize.Width-check.Width-16),0);
        text.Click+=(_,_)=>{if(check.Enabled)check.Checked=!check.Checked;};
        check.EnabledChanged+=(_,_)=>text.ForeColor=check.Enabled?Ink:Muted;
        return row;
    }
    private static void Wrap(Control parent,int width)
    {
        foreach(Control child in parent.Controls)
        {
            if(child is Label label && label.AutoSize){int available=parent.ClientSize.Width-parent.Padding.Horizontal-8;if(parent.Tag is CheckBox marker)available-=marker.Width+8;label.MaximumSize=new Size(Math.Max(100,Math.Min(width,available)),0);}
            if(child is CheckBox check)check.MaximumSize=new Size(width-38,0);
            if(child.HasChildren)Wrap(child,width-32);
        }
    }
    private void OpenPreparation(){if(busy)return;using var dialog=new OpenFileDialog{Title="Open fresh Crema preparation",Filter="Crema preparation (*.zip;*.crema)|*.zip;*.crema",CheckFileExists=true};if(dialog.ShowDialog(this)==DialogResult.OK)Read(dialog.FileName);}
    private void Read(string path)
    {
        if(busy)return;
        RefreshArtisanStatus();preparation=null;folder=null;progress=new();ready.Checked=curve.Checked=alarms.Checked=false;
        try
        {
            var value=Preparation.Read(path,DateTimeOffset.UtcNow);Directory.CreateDirectory(stateRoot);folder=value.Materialize(stateRoot);preparation=value;zipPath.Text=path;
            coffee.Text=value.Coffee;roast.Text=$"{value.Roast} roast · Plan #{value.Plan} / Load #{value.Row}";
            machine.Text=value.Roaster;weight.Text=value.Green.ToString("0.0",CultureInfo.InvariantCulture)+" oz";schedule.Text=value.Mode=="first"?"First · cold / 10+ min":"Second · warm";
            charge.Text=value.Charge.ToString("0.0",CultureInfo.InvariantCulture);drop.Text=value.Drop.ToString("0.0",CultureInfo.InvariantCulture);off.Text=value.Off.ToString("0.0",CultureInfo.InvariantCulture);
            local.Text="Downloaded "+value.Created.ToLocalTime().ToString("g");title.Text=value.Title;
            SetStatus("Review this load, then load its background.");
        }
        catch(Exception e){coffee.Text="Preparation could not be opened";roast.Text="Choose a fresh ZIP from your Crema portal.";machine.Text=weight.Text=schedule.Text=charge.Text=drop.Text=off.Text="—";title.Text="Roast title appears here";local.Text="No preparation open";SetStatus(e is InvalidDataException && e.Message.Contains("Central Directory",StringComparison.OrdinalIgnoreCase)?"This file is not a readable preparation ZIP. Download a fresh copy from Crema.":e.Message,true);}
        UpdateControls();
    }
    private bool ChooseArtisan()
    {
        using var dialog=new OpenFileDialog{Title="Choose your installed artisan.exe",Filter="Artisan (artisan.exe)|artisan.exe",CheckFileExists=true};if(dialog.ShowDialog(this)!=DialogResult.OK)return false;
        try{ArtisanTransport.InspectExecutable(dialog.FileName);}catch(Exception e){SetStatus(e.Message,true);return false;}
        artisan=dialog.FileName;RefreshArtisanStatus();
        try{Directory.CreateDirectory(stateRoot);File.WriteAllText(Path.Combine(stateRoot,"settings.json"),JsonSerializer.Serialize(new{artisan}));SetStatus("Artisan location remembered for this Windows user.");return true;}
        catch(Exception e){SetStatus("Could not save the Artisan location: "+e.Message,true);return false;}
    }
    private void LoadSettings(){try{string file=Path.Combine(stateRoot,"settings.json");if(File.Exists(file) && new FileInfo(file).Length<8192){using var d=JsonDocument.Parse(File.ReadAllText(file));artisan=d.RootElement.GetProperty("artisan").GetString()??"";}}catch{artisan="";}}
    private void RefreshArtisanStatus()
    {
        try{if(string.IsNullOrWhiteSpace(artisan) || !File.Exists(artisan))artisan=ArtisanTransport.FindInstalled()??"";
            if(string.IsNullOrWhiteSpace(artisan)){artisanStatus.Text="Choose Artisan under Help & settings";return;}
            var version=ArtisanTransport.InspectExecutable(artisan);artisanStatus.Text=$"Artisan {version.ToString(3)} selected · confirm monitoring OFF below";}
        catch(Exception e){artisanStatus.Text=e.Message;}
    }
    private async Task Next()
    {
        if(busy)return;
        if(progress.Stage is HandoffStage.Verified or HandoffStage.Uncertain){OpenPreparation();return;}
        if(progress.Stage==HandoffStage.AlarmsSent){try{progress.Verify(alarms.Checked);SetStatus("Preparation verified by you. Start the roast in Artisan.");}catch(Exception e){SetStatus(e.Message,true);}UpdateControls();return;}
        if(preparation==null || folder==null || !progress.CanSend(ready.Checked,curve.Checked))return;
        busy=true;UpdateControls();bool attempted=false;
        try
        {
            preparation.CheckAge(DateTimeOffset.UtcNow);using var pipe=await ArtisanTransport.ConnectMain();
            if(pipe==null)
            {
                if(ArtisanTransport.IsRunning())throw new IOException("Artisan is running but its main connection is unavailable. Finish startup dialogs and retry as the same normal Windows user.");
                if(progress.Stage!=HandoffStage.Review)throw new IOException("Artisan closed after the background request. Open a fresh preparation and start again.");
                if(!File.Exists(artisan) && !ChooseArtisan())return;
                ArtisanTransport.Start(artisan);SetStatus("Artisan is opening. No preparation has been sent.");
                var deadline=DateTime.UtcNow.AddSeconds(45);bool found=false;
                while(DateTime.UtcNow<deadline && !IsDisposed){await Task.Delay(350);using var candidate=await ArtisanTransport.ConnectMain();if(candidate!=null){found=true;break;}}
                if(IsDisposed)return;ready.Checked=false;SetStatus(found?"Artisan opened. Finish startup and check monitoring OFF before continuing.":"Finish Artisan startup, check readiness and retry.",!found);return;
            }
            if(IsDisposed)return;artisanStatus.Text=ArtisanTransport.ConnectedDescription;
            bool background=progress.Stage==HandoffStage.Review;string file=background?"reference.alog":"alarms.alrm";
            if(!File.ReadAllBytes(Path.Combine(folder,file)).SequenceEqual(preparation.Data[file]))throw new IOException("A local preparation file changed. Open the fresh ZIP again.");
            attempted=true;await ArtisanTransport.Send(pipe,Path.Combine(folder,file),background);if(IsDisposed)return;
            progress.Sent(background,ready.Checked,curve.Checked);
            if(background){curve.Checked=false;SetStatus("Background sent — check its curve in Artisan.");}
            else{alarms.Checked=false;SetStatus("Alarms sent — verify the three targets in Artisan.");}
        }
        catch(Exception e){if(!IsDisposed){if(attempted)progress.Uncertain();SetStatus(e.Message+(attempted?" Delivery is uncertain. Inspect Artisan before opening a fresh preparation.":""),true);}}
        finally{busy=false;if(!IsDisposed)UpdateControls();}
    }
    private void UpdateControls()
    {
        var stage=progress.Stage;open.Enabled=choose.Enabled=zipPath.Enabled=!busy;copy.Enabled=!busy && preparation!=null;
        readyRow.Visible=stage==HandoffStage.Review;curveRow.Visible=stage==HandoffStage.BackgroundSent;alarmsRow.Visible=stage==HandoffStage.AlarmsSent;
        ready.Enabled=!busy && preparation!=null && stage==HandoffStage.Review;curve.Enabled=!busy && stage==HandoffStage.BackgroundSent;alarms.Enabled=!busy && stage==HandoffStage.AlarmsSent;
        load.Text=busy?"Sending…":stage switch{HandoffStage.Review=>"Load background",HandoffStage.BackgroundSent=>"Load paired alarms",HandoffStage.AlarmsSent=>"Finish preparation",HandoffStage.Verified=>"Open next preparation",_=>"Open a fresh preparation"};load.AccessibleName=load.Text;
        load.Enabled=!busy && (stage is HandoffStage.Verified or HandoffStage.Uncertain || preparation!=null && (stage==HandoffStage.AlarmsSent?alarms.Checked:progress.CanSend(ready.Checked,curve.Checked)));
        load.BackColor=load.Enabled?Green:Color.FromArgb(225,229,223);load.ForeColor=load.Enabled?Color.White:Muted;
        instruction.Text=stage switch{HandoffStage.Review=>"Check this summary against the current Crema plan.",HandoffStage.BackgroundSent=>"Confirm the expected curve before sending its paired alarms.",HandoffStage.AlarmsSent=>"Config → Alarms: compare Charge, Drop and Off. Artisan 4: use Standard mode if hidden.",HandoffStage.Verified=>"Copy the title into Roast → Properties → Title. Photo and .alog uploads stay in Crema.",_=>"Do not retry blindly. Inspect Artisan, then open a fresh preparation."};
        int active=preparation==null?0:stage switch{HandoffStage.Review=>1,HandoffStage.BackgroundSent=>2,_=>3};
        string[] names=["PREPARATION","BACKGROUND","ALARMS","VERIFY"];
        for(int i=0;i<4;i++){bool done=i<active || stage==HandoffStage.Verified;steps[i].Text=$"{(done?"✓":(i+1).ToString())}  {names[i]}";steps[i].BackColor=i==active?Green:done?Color.FromArgb(220,232,221):Color.FromArgb(232,232,226);steps[i].ForeColor=i==active?Color.White:done?Ink:Muted;}
    }
    private void SetStatus(string text,bool error=false){status.Text=text;status.AccessibleName=text;status.ForeColor=error?Color.FromArgb(157,43,35):Ink;}
}
