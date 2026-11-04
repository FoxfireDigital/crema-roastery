using System.Diagnostics;
using System.IO.Pipes;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Text;

namespace CremaCompanion;

// This channel accepts one fixed wake gesture. No paths, credentials or roast commands.
internal static class WindowActivation
{
    internal static string PipeName
    {
        get
        {
            string sid=WindowsIdentity.GetCurrent().User?.Value??throw new IOException("Windows user identity unavailable.");
            return "crema-activate-"+Process.GetCurrentProcess().SessionId+"-"+Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(sid)))[..20];
        }
    }
    internal static async Task<bool> Wake(string name)
    {
        try
        {
            using var client=new NamedPipeClientStream(".",name,PipeDirection.Out,PipeOptions.Asynchronous|PipeOptions.CurrentUserOnly);
            using var timeout=new CancellationTokenSource(TimeSpan.FromSeconds(2));
            await client.ConnectAsync(timeout.Token);await client.WriteAsync("show\n"u8.ToArray(),timeout.Token);await client.FlushAsync(timeout.Token);return true;
        }
        catch(Exception ex)when(ex is IOException or OperationCanceledException or UnauthorizedAccessException){return false;}
    }
    internal static async Task Listen(string name,Action show,CancellationToken stop)
    {
        while(!stop.IsCancellationRequested)
        {
            try
            {
                using var server=new NamedPipeServerStream(name,PipeDirection.In,1,PipeTransmissionMode.Byte,PipeOptions.Asynchronous|PipeOptions.CurrentUserOnly);
                await server.WaitForConnectionAsync(stop);
                using var timeout=CancellationTokenSource.CreateLinkedTokenSource(stop);timeout.CancelAfter(TimeSpan.FromSeconds(2));
                var bytes=new byte[5];int filled=0;
                while(filled<bytes.Length){int count=await server.ReadAsync(bytes.AsMemory(filled),timeout.Token);if(count==0)break;filled+=count;}
                if(filled==5 && bytes.AsSpan().SequenceEqual("show\n"u8) && !stop.IsCancellationRequested)show();
            }
            catch(OperationCanceledException)when(stop.IsCancellationRequested){break;}
            catch(Exception ex)when(ex is IOException or OperationCanceledException or UnauthorizedAccessException)
            {try{await Task.Delay(200,stop);}catch(OperationCanceledException){break;}}
        }
    }
}
