// SayScorePDF.exe: starts the bootstrap script without a console window and
// shows a small startup window until the app's own window appears.
// Built with the .NET Framework compiler that ships with Windows (AnyCPU, C# 5),
// so the same file runs natively on x64 and ARM64 without extra runtimes.
//
//   SayScorePDF.exe            start, or bring the running app to the front
//   SayScorePDF.exe /restart   wait for the running app to close, then start
//
// The startup scripts report their current step through the file named in
// SAYSCORE_PROGRESS; the window shows it.
using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Threading;
using System.Windows.Forms;

[assembly: AssemblyTitle("SayScore PDF")]
[assembly: AssemblyProduct("SayScore PDF")]
[assembly: AssemblyDescription("SayScore PDF launcher")]

static class SayScoreLauncher
{
    // Created by easy_output.app while the app runs.
    const string AppMutex = "Local\\SayScorePDF.App";
    const string LauncherMutex = "Local\\SayScorePDF.Launcher";

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    static extern IntPtr FindWindow(string className, string windowName);
    [DllImport("user32.dll")]
    static extern bool ShowWindow(IntPtr window, int command);
    [DllImport("user32.dll")]
    static extern bool SetForegroundWindow(IntPtr window);
    [DllImport("user32.dll")]
    static extern bool IsWindowVisible(IntPtr window);
    [DllImport("user32.dll")]
    static extern bool SetProcessDPIAware();

    static bool AppRunning()
    {
        Mutex existing;
        if (!Mutex.TryOpenExisting(AppMutex, out existing)) return false;
        existing.Dispose();
        return true;
    }

    // The tkinter main window ("TkTopLevel"), not a message box with the same title.
    static IntPtr AppWindow()
    {
        IntPtr window = FindWindow("TkTopLevel", "SayScore PDF");
        return window != IntPtr.Zero && IsWindowVisible(window) ? window : IntPtr.Zero;
    }

    [STAThread]
    static int Main(string[] args)
    {
        bool restart = args.Length > 0 && args[0].Equals("/restart", StringComparison.OrdinalIgnoreCase);
        if (restart)
        {
            for (int i = 0; i < 150 && AppRunning(); i++) Thread.Sleep(100);
        }
        if (AppRunning())
        {
            IntPtr window = FindWindow("TkTopLevel", "SayScore PDF");
            if (window != IntPtr.Zero)
            {
                ShowWindow(window, 9);
                SetForegroundWindow(window);
            }
            return 0;
        }
        bool created;
        using (var launching = new Mutex(true, LauncherMutex, out created))
        {
            if (!created) return 0;  // another launch is already starting the app
            try { SetProcessDPIAware(); } catch (EntryPointNotFoundException) { }
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);

            string root = AppDomain.CurrentDomain.BaseDirectory;
            string bootstrap = Path.Combine(root, "scripts", "Bootstrap-SayScore.ps1");
            string powershell = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System),
                                             "WindowsPowerShell", "v1.0", "powershell.exe");
            string progress = Path.Combine(Path.GetTempPath(), "SayScorePDF-startup-" + Guid.NewGuid().ToString("N") + ".txt");
            Process process;
            try
            {
                if (!File.Exists(bootstrap))
                    throw new FileNotFoundException("프로그램 파일이 없습니다. 다시 설치하거나 압축을 완전히 푸세요.", bootstrap);
                var start = new ProcessStartInfo(powershell,
                    "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File \"" + bootstrap + "\" -NoShortcut");
                start.UseShellExecute = false;
                start.CreateNoWindow = true;
                start.WorkingDirectory = root;
                start.EnvironmentVariables["SAYSCORE_PROGRESS"] = progress;
                process = Process.Start(start);
            }
            catch (Exception error)
            {
                MessageBox.Show("SayScore PDF를 시작하지 못했습니다.\n\n" + error.Message, "SayScore PDF",
                                MessageBoxButtons.OK, MessageBoxIcon.Error);
                return 1;
            }
            Application.Run(new StartupWindow(process, progress));
            try { File.Delete(progress); } catch (IOException) { } catch (UnauthorizedAccessException) { }
            return 0;
        }
    }

    sealed class StartupWindow : Form
    {
        readonly Process process;
        readonly string progress;
        readonly Label status;
        readonly System.Windows.Forms.Timer timer;
        DateTime started = DateTime.UtcNow;
        DateTime exited = DateTime.MinValue;

        public StartupWindow(Process process, string progress)
        {
            this.process = process;
            this.progress = progress;
            Text = "SayScore PDF 시작 중";
            try { Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath); } catch (ArgumentException) { }
            FormBorderStyle = FormBorderStyle.FixedSingle;
            MaximizeBox = false;
            MinimizeBox = true;
            StartPosition = FormStartPosition.CenterScreen;
            // Fonts (in points) follow the display scale in this DPI-aware process;
            // scale the pixel layout by hand to match.
            AutoScaleMode = AutoScaleMode.None;
            float scale;
            using (Graphics graphics = CreateGraphics()) scale = graphics.DpiX / 96F;
            Func<int, int> px = delegate(int value) { return (int)Math.Round(value * scale); };
            BackColor = Color.White;
            ClientSize = new Size(px(400), px(136));
            Font = new Font("Malgun Gothic", 9.5F);

            var title = new Label();
            title.Text = "SayScore PDF를 시작하는 중입니다";
            title.Font = new Font("Malgun Gothic", 12F, FontStyle.Bold);
            title.ForeColor = Color.FromArgb(0x1b, 0x18, 0x40);
            title.AutoSize = true;
            title.Location = new Point(px(20), px(16));

            status = new Label();
            status.Text = "준비하는 중…";
            status.ForeColor = Color.FromArgb(0x5d, 0x5a, 0x7a);
            status.AutoSize = false;
            status.Location = new Point(px(20), px(50));
            status.Size = new Size(px(360), px(44));

            var bar = new ProgressBar();
            bar.Style = ProgressBarStyle.Marquee;
            bar.MarqueeAnimationSpeed = 30;
            bar.Location = new Point(px(20), px(104));
            bar.Size = new Size(px(360), px(10));

            Controls.Add(title);
            Controls.Add(status);
            Controls.Add(bar);

            timer = new System.Windows.Forms.Timer();
            timer.Interval = 300;
            timer.Tick += delegate { Poll(); };
            timer.Start();
        }

        void Poll()
        {
            if (AppWindow() != IntPtr.Zero) { Close(); return; }
            try
            {
                if (File.Exists(progress))
                {
                    string text = File.ReadAllText(progress).Trim();
                    if (text.Length > 0 && text != status.Text) status.Text = text;
                }
            }
            catch (IOException) { }
            catch (UnauthorizedAccessException) { }
            if (process.HasExited)
            {
                // A failed or finished-without-app start has already shown its own message.
                if (process.ExitCode != 0) { Close(); return; }
                if (exited == DateTime.MinValue) exited = DateTime.UtcNow;
                if ((DateTime.UtcNow - exited).TotalSeconds > 60) Close();
            }
            else if ((DateTime.UtcNow - started).TotalMinutes > 15)
            {
                Close();
            }
        }
    }
}
