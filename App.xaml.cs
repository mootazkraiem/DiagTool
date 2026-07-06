using System.Windows;
using System.Windows.Threading;
using System.Diagnostics;
using System.IO;
using System.Net.Http;
using CANvision.Native.Models;
using CANvision.Native.Services;
using CANvision.Native.UI;
using CANvision.Native.ViewModels;

namespace CANvision.Native;

public partial class App : Application
{
    private AppLogger? logger;
    private VehicleDataService? vehicleDataService;
    private Process? backendProcess;
    private bool backendStartedByApp;

    protected override void OnStartup(StartupEventArgs e)
    {
        base.OnStartup(e);

        logger = new AppLogger();
        
        // Add global exception handlers
        AppDomain.CurrentDomain.UnhandledException += (s, args) => 
            logger.Error("Unhandled Domain Exception", args.ExceptionObject as Exception);
        
        DispatcherUnhandledException += (s, args) => {
            logger.Error("Unhandled Dispatcher Exception", args.Exception);
            args.Handled = true;
        };

        logger.Info("Application startup sequence initiated.");

        var appConfig = AppConfig.Load();
        if (!string.IsNullOrWhiteSpace(appConfig.GoogleApiKey))
            Environment.SetEnvironmentVariable("GOOGLE_API_KEY", appConfig.GoogleApiKey);

        var pythonApiClient = new PythonApiClient(logger);
        vehicleDataService = new VehicleDataService(pythonApiClient, logger);
        var canLogImportService = new CanLogImportService(logger, pythonApiClient);

        var settings = new SettingsViewModel(vehicleDataService, pythonApiClient);
        var preview = new PreviewViewModel(null);

        var home = new HomeViewModel(vehicleDataService, canLogImportService, pythonApiClient);
        var dashboard = new DashboardViewModel(vehicleDataService);
        var telemetry = new TelemetryViewModel(vehicleDataService, canLogImportService);
        var diagnostics = new DiagnosticsViewModel(vehicleDataService);
        var playback = new LogPlaybackViewModel(vehicleDataService, canLogImportService, logger);
        var anomalyIntel = new AnomalyIntelViewModel(vehicleDataService, pythonApiClient);

        var navigationService = new NavigationService(
            logger,
            home,
            dashboard,
            telemetry,
            diagnostics,
            playback,
            settings,
            preview,
            anomalyIntel,
            vehicleDataService);
        preview.AttachNavigationService(navigationService);

        // Start at Garage (Home section shown inside the Interface layer)
        navigationService.NavigateToGarageCommand.Execute(null);
        logger.Info("Startup navigation set to Garage.");

        // When replay analysis completes → go straight to Anomaly Intel
        home.AnalysisCompleted += () =>
        {
            Dispatcher.BeginInvoke((System.Action)(() =>
            {
                navigationService.NavigateTo("AnomalyIntel");
            }));
        };

        // Online Diagnosis card clicked → unlock all tabs + go to Dashboard
        home.OnlineDiagnosisRequested += () =>
        {
            Dispatcher.BeginInvoke((System.Action)(() =>
            {
                vehicleDataService.Start();
                navigationService.EnterLiveMode();
            }));
        };


        var mainWindowViewModel = new MainWindowViewModel(
            navigationService,
            vehicleDataService);

        logger.Info("Initializing MainWindow...");
        var window = new MainWindow(mainWindowViewModel, logger);
        window.Show();
        window.Activate();
        window.Focus();
        MainWindow = window;

        // Start backend health check off the UI thread so it never blocks window rendering
        System.Threading.Tasks.Task.Run(() => EnsureBackendAvailable());
        
        logger.Info("Displaying MainWindow...");
        logger.Info($"IsVisible: {window.IsVisible}");
        logger.Info($"State: {window.WindowState}");
        logger.Info($"Size: {window.Width}x{window.Height}");

        logger.Info("Vehicle polling remains idle until replay import starts analysis.");

        logger.Info("Application startup sequence completed.");
    }

    protected override void OnExit(ExitEventArgs e)
    {
        logger?.Info($"Application exiting with code {e.ApplicationExitCode}.");
        vehicleDataService?.Stop();
        StopManagedBackend();
        base.OnExit(e);
    }

    /// <summary>
    /// Resolves the Python executable to use for the backend.
    /// Priority: project venv → system PATH → Windows py launcher.
    /// </summary>
    private static string? FindPythonExecutable(string projectRoot)
    {
        // 1. Project virtual environment (most reliable — exact version + packages)
        var venvPython = Path.Combine(projectRoot, "can_env", "Scripts", "python.exe");
        if (File.Exists(venvPython))
            return venvPython;

        // 2. System-installed Python on PATH
        foreach (var candidate in new[] { "python.exe", "python3.exe" })
        {
            try
            {
                var which = Process.Start(new ProcessStartInfo
                {
                    FileName = "where",
                    Arguments = candidate,
                    UseShellExecute = false,
                    CreateNoWindow = true,
                    RedirectStandardOutput = true,
                });
                var path = which?.StandardOutput.ReadLine()?.Trim();
                which?.WaitForExit(2000);
                if (!string.IsNullOrEmpty(path) && File.Exists(path))
                    return path;
            }
            catch { /* where.exe not available */ }
        }

        // 3. Windows Python Launcher
        var pyLauncher = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.Windows), "py.exe");
        if (File.Exists(pyLauncher))
            return pyLauncher;

        return null;
    }

    private void KillOrphanedBackendProcesses()
    {
        try
        {
            // Find PIDs listening on port 8765 via netstat and kill them.
            var psi = new ProcessStartInfo("netstat", "-ano")
            {
                UseShellExecute = false,
                CreateNoWindow = true,
                RedirectStandardOutput = true,
            };
            using var ps = Process.Start(psi);
            if (ps is null) return;
            var output = ps.StandardOutput.ReadToEnd();
            ps.WaitForExit(3000);

            foreach (var line in output.Split('\n'))
            {
                if (!line.Contains(":8765") || !line.Contains("LISTENING")) continue;
                var parts = line.Trim().Split(new char[] { ' ' }, StringSplitOptions.RemoveEmptyEntries);
                if (parts.Length < 5 || !int.TryParse(parts[parts.Length - 1], out var pid) || pid <= 4) continue;
                try
                {
                    using var victim = Process.GetProcessById(pid);
                    if (victim.ProcessName.Contains("python", StringComparison.OrdinalIgnoreCase))
                    {
                        victim.Kill();
                        logger?.Info($"Killed orphaned backend process PID {pid}.");
                    }
                }
                catch { /* process already gone */ }
            }

            System.Threading.Thread.Sleep(400);
        }
        catch (Exception ex)
        {
            logger?.Info($"KillOrphanedBackendProcesses skipped: {ex.Message}");
        }
    }

    private void EnsureBackendAvailable()
    {
        if (logger is null) return;

        if (IsBackendHealthy())
        {
            logger.Info("Python backend already available on 127.0.0.1:8765.");
            return;
        }

        // Port is occupied by an unresponsive orphaned Python process — kill it before starting fresh.
        KillOrphanedBackendProcesses();

        var projectRoot = Path.GetFullPath(Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "..", "..", ".."));
        var pythonExe = FindPythonExecutable(projectRoot);

        if (pythonExe is null)
        {
            logger.Error("Python executable not found. Backend cannot start.");
            Dispatcher.BeginInvoke(new System.Action(() =>
                System.Windows.MessageBox.Show(
                    "Python was not found on this machine.\n\n" +
                    "Please install Python 3.11+ and run:\n  pip install -r requirements.txt\n\n" +
                    "Or ensure the 'can_env' virtual environment exists in the project folder.",
                    "CANvision — Backend Unavailable",
                    System.Windows.MessageBoxButton.OK,
                    System.Windows.MessageBoxImage.Warning)));
            return;
        }

        // py.exe (launcher) needs an explicit version flag
        var isPyLauncher = Path.GetFileName(pythonExe).Equals("py.exe", StringComparison.OrdinalIgnoreCase);
        var args = isPyLauncher
            ? "-3 -m uvicorn backend.api.server:app --host 127.0.0.1 --port 8765"
            : "-m uvicorn backend.api.server:app --host 127.0.0.1 --port 8765";

        var psi = new ProcessStartInfo
        {
            FileName = pythonExe,
            Arguments = args,
            WorkingDirectory = projectRoot,
            UseShellExecute = false,
            CreateNoWindow = true,
            WindowStyle = ProcessWindowStyle.Hidden,
        };

        try
        {
            backendProcess = Process.Start(psi);
            backendStartedByApp = backendProcess is not null;
            logger.Info($"Started managed FastAPI backend (python: {pythonExe}).");
        }
        catch (Exception ex)
        {
            logger.Error("Failed to start managed FastAPI backend process.", ex);
            return;
        }

        var deadline = DateTime.UtcNow.AddSeconds(20);
        while (DateTime.UtcNow < deadline)
        {
            if (IsBackendHealthy())
            {
                logger.Info("Managed FastAPI backend is healthy.");
                return;
            }
            System.Threading.Thread.Sleep(300);
        }

        logger.Error("Managed FastAPI backend did not become healthy within 20 s.");
        Dispatcher.BeginInvoke(new System.Action(() =>
            System.Windows.MessageBox.Show(
                "The AI backend (Python/FastAPI) failed to start within 20 seconds.\n\n" +
                "Offline log analysis and AI features will be unavailable.\n" +
                "Check that all Python dependencies are installed:\n  pip install -r requirements.txt",
                "CANvision — Backend Timeout",
                System.Windows.MessageBoxButton.OK,
                System.Windows.MessageBoxImage.Warning)));
    }

    private static bool IsBackendHealthy()
    {
        try
        {
            // Use Task.Run to avoid deadlocking the WPF SynchronizationContext
            return System.Threading.Tasks.Task.Run(async () =>
            {
                using var client = new HttpClient { Timeout = TimeSpan.FromSeconds(1.2) };
                using var response = await client.GetAsync("http://127.0.0.1:8765/health").ConfigureAwait(false);
                return response.IsSuccessStatusCode;
            }).GetAwaiter().GetResult();
        }
        catch
        {
            return false;
        }
    }

    private void StopManagedBackend()
    {
        if (!backendStartedByApp || backendProcess is null) return;

        try
        {
            if (backendProcess.HasExited)
            {
                logger?.Info("Backend process already exited.");
                return;
            }

            // Give uvicorn a moment to flush logs before killing
            backendProcess.Kill();
            if (!backendProcess.WaitForExit(5000))
            {
                // Process still alive after 5 s — log and move on (OS will clean up on app exit)
                logger?.Error("Backend process did not terminate within 5 s after Kill().");
                return;
            }

            logger?.Info($"Stopped managed FastAPI backend (exit code {backendProcess.ExitCode}).");
        }
        catch (Exception ex)
        {
            logger?.Error("Error stopping backend process.", ex);
        }
        finally
        {
            backendProcess.Dispose();
            backendProcess = null;
        }
    }
}
