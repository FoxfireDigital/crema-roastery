using System.Diagnostics;
using System.IO.Pipes;
using System.Runtime.InteropServices;
using System.Text;

namespace CremaCompanion;

internal static class ArtisanTransport
{
    // Reviewed in Artisan 3.1.0 and exact v4.0.2 source; never use the viewer endpoint.
    internal const string MainPipe="9068bd2fa8e54945a6be1f1a0a589e92";
    internal static string ConnectedDescription { get; private set; } = "";
    internal static bool Supports(Version? version) => version != null &&
        ((version.Major == 3 && version.Minor == 1 && version.Build == 0) ||
         (version.Major == 4 && version.Minor == 0 && version.Build == 2));

    internal static Version InspectExecutable(string executable)
    {
        if (string.IsNullOrWhiteSpace(executable) || Path.GetFullPath(executable).StartsWith("\\\\",StringComparison.Ordinal) ||
            !File.Exists(executable) || !Path.GetFileName(executable).Equals("artisan.exe",StringComparison.OrdinalIgnoreCase))
            throw new IOException("Choose the installed local artisan.exe.");
        var info=FileVersionInfo.GetVersionInfo(executable);
        if (!string.Equals(info.ProductName,"Artisan",StringComparison.OrdinalIgnoreCase) ||
            !Version.TryParse(info.FileVersion,out var version) || !Supports(version))
            throw new IOException("This pilot has reviewed Artisan 3.1.0 and 4.0.2. Choose one of those installed versions; other releases need a compatibility check first.");
        return version;
    }
    internal static string? FindInstalled()
    {
        foreach (var root in new[]{Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles),Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86)}.Where(x=>!string.IsNullOrWhiteSpace(x)).Distinct())
        {
            string path=Path.Combine(root,"Artisan","artisan.exe");
            try { InspectExecutable(path);return path; } catch(IOException) { }
        }
        return null;
    }
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
            using var caller=Process.GetCurrentProcess();
            if(server.SessionId!=caller.SessionId)throw new IOException("Artisan belongs to another Windows session. Use the copy open on this desktop.");
            try
            {
                string executable=server.MainModule?.FileName ?? throw new IOException("Artisan's executable could not be verified.");
                var version=InspectExecutable(executable);
                ConnectedDescription=$"Last handoff target: Artisan {version.ToString(3)} · existing main window";
            }
            catch(System.ComponentModel.Win32Exception)
            {
                throw new IOException("Cannot verify Artisan's executable. Run Artisan and Crema Companion as the same normal Windows user.");
            }
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
        InspectExecutable(executable);
        if(IsRunning())throw new IOException("Artisan is already running. Finish its startup dialogs and retry; a second copy was not opened.");
        Process.Start(new ProcessStartInfo(executable){UseShellExecute=false,WorkingDirectory=Path.GetDirectoryName(executable)!});
    }
}
