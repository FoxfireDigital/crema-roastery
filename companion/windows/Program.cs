namespace CremaCompanion;

internal static class Program
{
    [STAThread]
    private static int Main(string[] args)
    {
        if(args.Length==2 && args[0]=="--self-test") return PilotChecks.Run(args[1]);
        ApplicationConfiguration.Initialize();
        using var mutex=new Mutex(false,"Local\\CremaCompanionPilot");
        bool owned=false;
        try
        {
            try{owned=mutex.WaitOne(0);}catch(AbandonedMutexException){owned=true;}
            if(!owned){if(!WindowActivation.Wake(WindowActivation.PipeName).GetAwaiter().GetResult())MessageBox.Show("Crema Companion is already running. Open it using the coffee icon in the Windows tray.","Crema Companion",MessageBoxButtons.OK,MessageBoxIcon.Information);return 0;}
            if(args.Length>1)throw new ArgumentException("Open one preparation ZIP at a time.");
            Application.Run(new CompanionWindow(args.FirstOrDefault()));return 0;
        }
        catch(Exception error){MessageBox.Show(error.Message,"Crema Companion stopped",MessageBoxButtons.OK,MessageBoxIcon.Error);return 1;}
        finally{if(owned)mutex.ReleaseMutex();}
    }
}
