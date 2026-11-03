using System.Diagnostics;
using System.IO.Pipes;
using System.Runtime.InteropServices;
using System.Text;

namespace CremaCompanion;

internal static class ArtisanTransport
{
    // Artisan 3.1 main application GUID, never its comparison/viewer endpoint.
    internal const string MainPipe="9068bd2fa8e54945a6be1f1a0a589e92";
    [DllImport("kernel32.dll",SetLastError=true)]
    [return:MarshalAs(UnmanagedType.Bool)]
    private static extern bool GetNamedPipeServerProcessId(Microsoft.Win32.SafeHandles.SafePipeHandle pipe,out uint pid);

    internal static async Task<NamedPipeClientStream?> ConnectMain()
    {
        var pipe=new NamedPipeClientStream(".",MainPipe,PipeDirection.Out,PipeOptions.Asynchronous);
        try
        {
            using var timeout=new CancellationTokenSource(500);
            await pipe.ConnectAsync(timeout.Token);
            if(!GetNamedPipeServerProcessId(pipe.SafePipeHandle,out uint pid))throw new IOException("Cannot identify Artisan's main connection.");
            using var server=Process.GetProcessById(checked((int)pid));
            if(!server.ProcessName.Equals("artisan",StringComparison.OrdinalIgnoreCase))throw new IOException("The main connection does not belong to Artisan.");
            return pipe;
        }
        catch(OperationCanceledException){pipe.Dispose();return null;}
        catch(TimeoutException){pipe.Dispose();return null;}
        catch{pipe.Dispose();throw;}
    }
    internal static bool IsRunning()
    {
        var processes=Process.GetProcessesByName("artisan");
        bool running=processes.Length>0;foreach(var process in processes)process.Dispose();return running;
    }
    internal static string FileMessage(string path,bool background)=>new Uri(Path.GetFullPath(path)).AbsoluteUri+(background?"?template":"")+"\n";
    internal static async Task Send(NamedPipeClientStream pipe,string path,bool background)
    {
        byte[] bytes=new UTF8Encoding(false,true).GetBytes(FileMessage(path,background));
        using var timeout=new CancellationTokenSource(3000);
        await pipe.WriteAsync(bytes,timeout.Token);await pipe.FlushAsync(timeout.Token);
        // This transport has no load or idle acknowledgement. Never call this "loaded".
    }
    internal static void Start(string executable)
    {
        if(!File.Exists(executable)||!Path.GetFileName(executable).Equals("artisan.exe",StringComparison.OrdinalIgnoreCase))
            throw new IOException("Choose the installed artisan.exe first.");
        if(IsRunning())throw new IOException("Artisan is already running. Finish its startup dialogs and retry; a second copy was not opened.");
        Process.Start(new ProcessStartInfo(executable){UseShellExecute=false,WorkingDirectory=Path.GetDirectoryName(executable)!});
    }
}
