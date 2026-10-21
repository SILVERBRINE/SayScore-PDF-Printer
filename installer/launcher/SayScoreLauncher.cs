// SayScorePDF.exe: starts the bootstrap script without a console window.
// Built with the .NET Framework compiler that ships with Windows (AnyCPU), so
// the same file runs natively on x64 and ARM64 without extra runtimes.
using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Windows.Forms;

[assembly: AssemblyTitle("SayScore PDF")]
[assembly: AssemblyProduct("SayScore PDF")]
[assembly: AssemblyDescription("SayScore PDF launcher")]

static class SayScoreLauncher
{
    [STAThread]
    static int Main()
    {
        string root = AppDomain.CurrentDomain.BaseDirectory;
        string bootstrap = Path.Combine(root, "scripts", "Bootstrap-SayScore.ps1");
        string powershell = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System),
                                         "WindowsPowerShell", "v1.0", "powershell.exe");
        try
        {
            if (!File.Exists(bootstrap))
                throw new FileNotFoundException("프로그램 파일이 없습니다. 다시 설치하거나 압축을 완전히 푸세요.", bootstrap);
            var start = new ProcessStartInfo(powershell,
                "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File \"" + bootstrap + "\" -NoShortcut")
            {
                UseShellExecute = false,
                CreateNoWindow = true,
                WorkingDirectory = root,
            };
            Process.Start(start);
            return 0;
        }
        catch (Exception error)
        {
            MessageBox.Show("SayScore PDF를 시작하지 못했습니다.\n\n" + error.Message, "SayScore PDF",
                            MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
    }
}
