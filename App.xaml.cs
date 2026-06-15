using System.Windows;
using System.Windows.Threading;
using System.Diagnostics;
using System.IO;
using System.Net.Http;
using CANvision.Native.Scene;
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

        var pythonApiClient = new PythonApiClient(logger);
        vehicleDataService = new VehicleDataService(pythonApiClient, logger);
        var canLogImportService = new CanLogImportService(logger, pythonApiClient);
        var backgroundManager = new BackgroundManager(logger);

        var analytics = new AnalyticsViewModel(vehicleDataService);
        var settings = new SettingsViewModel(vehicleDataService);
        var preview = new PreviewViewModel(null);

        var home = new HomeViewModel(vehicleDataService, canLogImportService, pythonApiClient);
        var dashboard = new DashboardViewModel(vehicleDataService);
        var telemetry = new TelemetryViewModel(vehicleDataService, canLogImportService);
        var diagnostics = new DiagnosticsViewModel(vehicleDataService);
        var playback = new LogPlaybackViewModel(vehicleDataService, canLogImportService, logger);
        var validationLab = new ValidationLabViewModel(vehicleDataService, canLogImportService, logger);
        var anomalyIntel = new AnomalyIntelViewModel(vehicleDataService, pythonApiClient);

        var navigationService = new NavigationService(
            logger,
            home,
            dashboard,
            telemetry,
            diagnostics,
            playback,
            analytics,
            settings,
            preview,
            validationLab,
            anomalyIntel,
            vehicleDataService);
        preview.AttachNavigationService(navigationService);

        // Start at Garage (Home section shown inside the Interface layer)
        navigationService.NavigateToGarageCommand.Execute(null);
        logger.Info("Startup navigation set to Garage.");

        // When replay analysis completes → advance to the Analysis Cards hub
        home.AnalysisCompleted += () =>
        {
            Dispatcher.BeginInvoke((System.Action)(() =>
            {
                if (ReferenceEquals(navigationService.CurrentSection, home) &&
                    navigationService.IsSystemVisible)
                {
                    navigationService.EnterSystemCommand.Execute(null);
                }
            }));
        };

        // Live session first data → advance to Cards once
        var liveSessionFired = false;
        vehicleDataService.DataUpdated += _ =>
        {
            if (liveSessionFired || !vehicleDataService.IsRunning) return;
            liveSessionFired = true;
            Dispatcher.BeginInvoke((System.Action)(() =>
            {
                if (ReferenceEquals(navigationService.CurrentSection, home) &&
                    navigationService.IsSystemVisible)
                {
                    navigationService.EnterSystemCommand.Execute(null);
                }
            }));
        };

        var mainWindowViewModel = new MainWindowViewModel(
            navigationService,
            vehicleDataService,
            backgroundManager);

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

    private void EnsureBackendAvailable()
    {
        if (logger is null)
        {
            return;
        }

        if (IsBackendHealthy())
        {
            logger.Info("Python backend already available on 127.0.0.1:8765.");
            return;
        }

        var projectRoot = Path.GetFullPath(Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "..", "..", ".."));
        var pythonExe = @"C:\Users\benkr\AppData\Local\Programs\Python\Python313\python.exe";

        ProcessStartInfo psi;
        if (File.Exists(pythonExe))
        {
            psi = new ProcessStartInfo
            {
                FileName = pythonExe,
                Arguments = "-m uvicorn backend.api.server:app --host 127.0.0.1 --port 8765",
                WorkingDirectory = projectRoot,
                UseShellExecute = false,
                CreateNoWindow = true,
                WindowStyle = ProcessWindowStyle.Hidden,
            };
        }
        else
        {
            psi = new ProcessStartInfo
            {
                FileName = "py",
                Arguments = "-3.13 -m uvicorn backend.api.server:app --host 127.0.0.1 --port 8765",
                WorkingDirectory = projectRoot,
                UseShellExecute = false,
                CreateNoWindow = true,
                WindowStyle = ProcessWindowStyle.Hidden,
            };
        }

        try
        {
            backendProcess = Process.Start(psi);
            backendStartedByApp = backendProcess is not null;
            logger.Info("Started managed FastAPI backend process.");
        }
        catch (Exception ex)
        {
            logger.Error("Failed to start managed FastAPI backend process.", ex);
            return;
        }

        var deadline = DateTime.UtcNow.AddSeconds(12);
        while (DateTime.UtcNow < deadline)
        {
            if (IsBackendHealthy())
            {
                logger.Info("Managed FastAPI backend is healthy.");
                return;
            }

            System.Threading.Thread.Sleep(300);
        }

        logger.Error("Managed FastAPI backend did not become healthy in time.");
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
        if (!backendStartedByApp || backendProcess is null)
        {
            return;
        }

        try
        {
            if (!backendProcess.HasExited)
            {
                backendProcess.Kill();
                backendProcess.WaitForExit(2000);
            }
            logger?.Info("Stopped managed FastAPI backend process.");
        }
        catch (Exception ex)
        {
            logger?.Error("Error stopping backend process.", ex);
        }
    }
}
