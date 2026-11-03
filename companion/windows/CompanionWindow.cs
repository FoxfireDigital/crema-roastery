using System.Globalization;
using System.IO.Pipes;
using System.Text.Json;

namespace CremaCompanion;

internal sealed class CompanionWindow : Form
{
    private readonly string stateRoot=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"CremaCompanionPilot");
    private readonly Button open=Button("Open preparation ZIP"), choose=Button("Choose Artisan"), load=Button("Load background"), copy=Button("Copy roast title");
    private readonly TextBox zipPath=new(){Dock=DockStyle.Fill,PlaceholderText="Drop a ZIP here, browse, or paste its local path",AccessibleName="Preparation ZIP path"};
    private readonly Label summary=Label("Open a fresh preparation downloaded from your Crema portal."), status=Label("No preparation open."), targets=Label(""), local=Label(""), title=Label("");
    private readonly CheckBox ready=new(){AutoSize=true,AccessibleName="Current plan checked, correct USB roaster, previous work saved, Artisan idle and monitoring OFF"};
    private readonly CheckBox curve=new(){AutoSize=true,AccessibleName="Expected background visible, Artisan idle and monitoring OFF",Visible=false};
    private readonly Label readinessText=Label("Current plan checked; correct USB roaster connected; previous work saved; Artisan idle with monitoring OFF.");
    private readonly Label curveText=Label("The expected background curve is visible, and Artisan is still idle with monitoring OFF.");
    private readonly TableLayoutPanel curveRow;
    private Preparation? preparation;
    private string? folder;
    private string artisan="";
    private int phase;
    private bool busy;
    private readonly string? initial;
    internal CompanionWindow(string? initialPath)
    {
        initial=initialPath;Text="Crema Companion — Pilot";Name="CremaCompanionPilot";
        Font=new Font("Segoe UI",10);AutoScaleMode=AutoScaleMode.Dpi;
        ClientSize=new Size(650,735);MinimumSize=new Size(520,640);StartPosition=FormStartPosition.CenterScreen;
        BackColor=Color.FromArgb(245,248,246);ForeColor=Color.FromArgb(29,57,46);AllowDrop=true;
        var layout=new TableLayoutPanel{Dock=DockStyle.Fill,AutoScroll=true,ColumnCount=1,Padding=new Padding(24),BackColor=BackColor};
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent,100));Controls.Add(layout);
        var heading=Label("CREMA COMPANION");heading.Font=new Font(Font.FontFamily,16,FontStyle.Bold);Add(layout,heading);
        Add(layout,Label("Portable pilot · Preparation files only · No portal sign-in needed",9));
        var files=new FlowLayoutPanel{AutoSize=true,Dock=DockStyle.Fill,WrapContents=true,Margin=new Padding(0,15,0,12)};files.Controls.Add(open);files.Controls.Add(choose);Add(layout,files);
        zipPath.Margin=new Padding(0,0,0,14);Add(layout,zipPath);
        summary.Font=new Font(Font.FontFamily,14,FontStyle.Bold);Add(layout,summary);
        Add(layout,targets);Add(layout,local);
        var titleRow=new TableLayoutPanel{AutoSize=true,Dock=DockStyle.Fill,ColumnCount=1,Margin=new Padding(0,12,0,8)};
        titleRow.Controls.Add(Label("Roast title",9));titleRow.Controls.Add(title);titleRow.Controls.Add(copy);Add(layout,titleRow);
        Add(layout,Label("Copy replaces clipboard text. Paste into Artisan → Roast → Properties → Title. This pilot does not set the active title automatically.",9));
        Add(layout,Label("Files are checked locally against their included checksums. Live plan changes cannot be detected: use a fresh download from your own portal and check the current plan.",9));
        Add(layout,CheckRow(ready,readinessText));
        curveRow=CheckRow(curve,curveText);curveRow.Visible=false;Add(layout,curveRow);
        load.BackColor=Color.FromArgb(35,80,60);load.ForeColor=Color.White;load.FlatStyle=FlatStyle.Flat;load.MinimumSize=new Size(210,44);Add(layout,load);
        status.Margin=new Padding(0,14,0,8);status.Font=new Font(Font.FontFamily,10,FontStyle.Bold);Add(layout,status);
        Add(layout,Label("A sent request is not a verified load. Check Charge / Drop / Off in Config → Alarms before roasting. Off stops Artisan monitoring; it does not guarantee a heater shutdown.",9));
        Add(layout,Label("No monitoring, recording or roast is started. Packing, stock and production records are unchanged.",9));
        open.Click+=(_,_)=>{if(!string.IsNullOrWhiteSpace(zipPath.Text)){Read(zipPath.Text.Trim().Trim('"'));return;}using var dialog=new OpenFileDialog{Title="Open fresh Crema preparation",Filter="Crema preparation (*.zip;*.crema)|*.zip;*.crema",CheckFileExists=true};if(dialog.ShowDialog(this)==DialogResult.OK)Read(dialog.FileName);};
        zipPath.KeyDown+=(_,e)=>{if(e.KeyCode==Keys.Enter && !busy){e.SuppressKeyPress=true;Read(zipPath.Text.Trim().Trim('"'));}};
        choose.Click+=(_,_)=>ChooseArtisan();load.Click+=async (_,_)=>await LoadPreparation();
        ready.CheckedChanged+=(_,_)=>UpdateControls();curve.CheckedChanged+=(_,_)=>UpdateControls();
        copy.Click+=(_,_)=>{try{if(preparation!=null){Clipboard.SetText(preparation.Title);SetStatus("Title copied. Paste it into Artisan's active roast Title.");}}catch(Exception e){SetStatus("Clipboard unavailable: "+e.Message,true);}};
        DragEnter+=(_,e)=>{if(!busy && e.Data?.GetData(DataFormats.FileDrop) is string[] paths && paths.Length==1)e.Effect=DragDropEffects.Copy;};
        DragDrop+=(_,e)=>{if(!busy && e.Data?.GetData(DataFormats.FileDrop) is string[] paths && paths.Length==1)Read(paths[0]);};
        layout.SizeChanged+=(_,_)=>{int width=Math.Max(300,layout.ClientSize.Width-60);foreach(var l in new[]{summary,status,targets,local,title})l.MaximumSize=new Size(width,0);readinessText.MaximumSize=new Size(width-32,0);curveText.MaximumSize=new Size(width-32,0);};
        LoadSettings();UpdateControls();Shown+=(_,_)=>{if(initial!=null)Read(initial);};
    }
    private static Label Label(string text,int size=10)=>new(){AutoSize=true,Text=text,MaximumSize=new Size(580,0),Margin=new Padding(0,0,0,9),Font=new Font("Segoe UI",size)};
    private static Button Button(string text)=>new(){AutoSize=true,Text=text,AccessibleName=text,Padding=new Padding(10,6,10,6),Margin=new Padding(0,0,10,4),UseVisualStyleBackColor=true};
    private static void Add(TableLayoutPanel layout,Control control){int row=layout.RowCount++;layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));layout.Controls.Add(control,0,row);}
    private static TableLayoutPanel CheckRow(CheckBox check,Label text)
    {
        var row=new TableLayoutPanel{AutoSize=true,Dock=DockStyle.Fill,ColumnCount=2,Margin=new Padding(0,10,0,8)};
        row.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));row.ColumnStyles.Add(new ColumnStyle(SizeType.Percent,100));
        check.Margin=new Padding(0,3,10,0);text.Margin=Padding.Empty;text.MaximumSize=new Size(548,0);
        row.Controls.Add(check,0,0);row.Controls.Add(text,1,0);
        text.Click+=(_,_)=>{if(check.Enabled)check.Checked=!check.Checked;};
        check.EnabledChanged+=(_,_)=>text.ForeColor=check.Enabled?SystemColors.ControlText:SystemColors.GrayText;
        return row;
    }
    private void Read(string path)
    {
        if(busy)return;
        preparation=null;folder=null;phase=0;ready.Checked=false;curve.Checked=false;curve.Visible=false;curveRow.Visible=false;
        try
        {
            var value=Preparation.Read(path,DateTimeOffset.UtcNow);
            Directory.CreateDirectory(stateRoot);folder=value.Materialize(stateRoot);preparation=value;zipPath.Text=path;
            summary.Text=$"{value.Coffee} · {value.Roast}\n{value.Roaster} · {value.Green.ToString("0.0",CultureInfo.InvariantCulture)} oz green · {(value.Mode=="first"?"First — cold / idle 10+ min":"Second — warm / continuing")}";
            targets.Text=$"Plan #{value.Plan} · Load #{value.Row}\nBT Charge {value.Charge:0.0} °F · Drop {value.Drop:0.0} °F · Off {value.Off:0.0} °F";
            local.Text="Downloaded "+value.Created.ToLocalTime().ToString("g")+" · three data files checked";
            title.Text=value.Title;SetStatus("Review the summary and readiness check, then load the background.");
        }
        catch(Exception e){summary.Text="Preparation could not be opened.";targets.Text="";local.Text="";title.Text="";SetStatus(e.Message,true);}
        UpdateControls();
    }
    private bool ChooseArtisan()
    {
        using var dialog=new OpenFileDialog{Title="Choose your installed artisan.exe",Filter="Artisan (artisan.exe)|artisan.exe",CheckFileExists=true};
        if(dialog.ShowDialog(this)!=DialogResult.OK)return false;
        if(!Path.GetFileName(dialog.FileName).Equals("artisan.exe",StringComparison.OrdinalIgnoreCase)){SetStatus("Choose artisan.exe.",true);return false;}
        artisan=dialog.FileName;
        try{Directory.CreateDirectory(stateRoot);File.WriteAllText(Path.Combine(stateRoot,"settings.json"),JsonSerializer.Serialize(new{artisan}));SetStatus("Artisan location remembered for this Windows user.");return true;}
        catch(Exception e){SetStatus("Could not save the Artisan location: "+e.Message,true);return false;}
    }
    private void LoadSettings()
    {
        try{string file=Path.Combine(stateRoot,"settings.json");if(File.Exists(file) && new FileInfo(file).Length<8192){using var d=JsonDocument.Parse(File.ReadAllText(file));artisan=d.RootElement.GetProperty("artisan").GetString()??"";}}catch{artisan="";}
    }
    private async Task LoadPreparation()
    {
        if(busy || preparation==null || folder==null || !ready.Checked || (phase==1 && !curve.Checked) || phase>=2)return;
        busy=true;UpdateControls();bool attempted=false;
        try
        {
            preparation.CheckAge(DateTimeOffset.UtcNow);
            using var pipe=await ArtisanTransport.ConnectMain();
            if(pipe==null)
            {
                if(ArtisanTransport.IsRunning())throw new IOException("Artisan is running but its main connection is unavailable. Finish startup dialogs and retry. Do not open a second copy or run either app as administrator.");
                if(phase!=0)throw new IOException("Artisan closed after the background request. Reopen the fresh preparation and start again.");
                if(!File.Exists(artisan) && !ChooseArtisan())return;
                ArtisanTransport.Start(artisan);SetStatus("Artisan is opening. No preparation has been sent.");
                var deadline=DateTime.UtcNow.AddSeconds(45);bool found=false;
                while(DateTime.UtcNow<deadline && !IsDisposed){await Task.Delay(350);using var candidate=await ArtisanTransport.ConnectMain();if(candidate!=null){found=true;break;}}
                if(IsDisposed)return;
                ready.Checked=false;
                SetStatus(found?"Artisan opened. Finish its dialogs, confirm monitoring OFF, then check readiness and load the background.":"Artisan has not exposed its main connection yet. Finish startup, check readiness and retry.",!found);return;
            }
            if(IsDisposed)return;
            string file=phase==0?"reference.alog":"alarms.alrm";
            // Recheck the stored payload before each send; never execute package scripts.
            if(!File.ReadAllBytes(Path.Combine(folder,file)).SequenceEqual(preparation.Data[file]))throw new IOException("A local preparation file changed. Open the fresh ZIP again.");
            attempted=true;await ArtisanTransport.Send(pipe,Path.Combine(folder,file),phase==0);
            if(IsDisposed)return;
            if(phase==0){phase=1;curve.Visible=true;curveRow.Visible=true;curve.Checked=false;SetStatus("Background request sent. Check its curve in Artisan; then confirm below to send the paired alarms.");}
            else{phase=2;SetStatus("Alarm request sent. Verify all three targets in Config → Alarms, and copy/paste the active roast title before roasting.");}
        }
        catch(Exception e){if(!IsDisposed){if(attempted)phase=3;SetStatus(e.Message+(attempted?" Delivery is uncertain. Inspect Artisan and reopen the preparation before retrying.":""),true);}}
        finally{busy=false;if(!IsDisposed)UpdateControls();}
    }
    private void UpdateControls()
    {
        open.Enabled=choose.Enabled=zipPath.Enabled=!busy;copy.Enabled=!busy && preparation!=null;
        ready.Enabled=!busy && preparation!=null && phase==0;curve.Enabled=!busy && phase==1;
        load.Text=busy?"Working…":phase==0?"Load background":phase==1?"Load paired alarms":phase==2?"Requests sent — verify in Artisan":"Reopen preparation to retry";
        load.AccessibleName=load.Text;
        load.Enabled=!busy && preparation!=null && ready.Checked && (phase==0 || phase==1 && curve.Checked);
        load.BackColor=load.Enabled?Color.FromArgb(35,80,60):SystemColors.Control;load.ForeColor=load.Enabled?Color.White:SystemColors.GrayText;
    }
    private void SetStatus(string text,bool error=false){status.Text=text;status.AccessibleName=text;status.ForeColor=error?Color.FromArgb(152,38,38):ForeColor;}
}
