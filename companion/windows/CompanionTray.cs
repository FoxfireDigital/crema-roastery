using System.Drawing.Drawing2D;
using System.Runtime.InteropServices;

namespace CremaCompanion;

internal sealed class CompanionTray : IDisposable
{
    private readonly NotifyIcon tray;
    private readonly ContextMenuStrip menu=new();
    private readonly Icon icon;
    private bool explained;
    internal CompanionTray(Action open,Action quick,Action exit)
    {
        icon=CreateIcon();
        menu.Items.Add("Open Companion",null,(_,_)=>open());
        menu.Items.Add("Quick view",null,(_,_)=>quick());menu.Items.Add(new ToolStripSeparator());
        menu.Items.Add("Exit Companion",null,(_,_)=>exit());
        tray=new NotifyIcon{Icon=icon,Text="Crema Companion",ContextMenuStrip=menu,Visible=true};
        tray.MouseClick+=(_,e)=>{if(e.Button==MouseButtons.Left)quick();};
    }
    internal Icon WindowIcon=>icon;
    internal void ExplainHidden()
    {
        if(explained)return;explained=true;
        tray.ShowBalloonTip(3500,"Crema is in the tray","Click the coffee icon for Quick view. Right-click it for Open Companion or Exit.",ToolTipIcon.Info);
    }
    internal void Status(string? coffee)
    {
        var text=string.IsNullOrWhiteSpace(coffee)?"Crema Companion":"Crema · "+coffee;
        tray.Text=text.Length>60?text[..57]+"…":text;
    }
    public void Dispose(){tray.Visible=false;tray.Dispose();menu.Dispose();icon.Dispose();}
    private static Icon CreateIcon()
    {
        using var image=new Bitmap(32,32);using var g=Graphics.FromImage(image);g.SmoothingMode=SmoothingMode.AntiAlias;
        g.Clear(Color.Transparent);using var background=new SolidBrush(Color.FromArgb(36,81,60));g.FillEllipse(background,1,1,30,30);
        using var pen=new Pen(Color.White,1.8f){StartCap=LineCap.Round,EndCap=LineCap.Round,LineJoin=LineJoin.Round};
        g.DrawLines(pen,[new PointF(8,12),new PointF(23,12),new PointF(23,21),new PointF(20,25),new PointF(11,25),new PointF(8,21),new PointF(8,12)]);
        g.DrawArc(pen,20,13,8,8,-90,180);g.DrawLine(pen,12,7,12,9);g.DrawLine(pen,17,6,17,9);g.DrawLine(pen,22,7,22,9);
        var handle=image.GetHicon();try{return (Icon)Icon.FromHandle(handle).Clone();}finally{DestroyIcon(handle);}
    }
    [DllImport("user32.dll")]private static extern bool DestroyIcon(IntPtr icon);
    [DllImport("dwmapi.dll")]private static extern int DwmSetWindowAttribute(IntPtr window,int attribute,ref int value,int size);
    internal static void RoundCorners(IntPtr window)
    {if(OperatingSystem.IsWindowsVersionAtLeast(10,0,22000)){int round=2;DwmSetWindowAttribute(window,33,ref round,sizeof(int));}}
}
