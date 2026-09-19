using System;
using System.ComponentModel;
using System.Windows;
using System.Windows.Media;
using CANvision.Native.Services;
using CANvision.Native.ViewModels;

namespace CANvision.Native.UI;

public partial class MainWindow : Window
{
    private readonly MainWindowViewModel viewModel;
    private readonly AppLogger logger;

    public MainWindow(MainWindowViewModel viewModel, AppLogger logger)
    {
        InitializeComponent();
        this.viewModel = viewModel;
        this.logger = logger;
        DataContext = viewModel;
        Loaded += OnLoaded;
        Closed += OnClosed;
    }

    private void OnLoaded(object sender, RoutedEventArgs e)
    {
        // WindowStyle stays None (set in XAML) - the nav bar is the chrome.
        ResizeMode = ResizeMode.CanResize;
        WindowState = WindowState.Maximized;
        InterfaceLayer.Opacity = 1.0;
        logger.Info($"CurrentSection: {viewModel.CurrentSection?.GetType().Name ?? "null"}");
        logger.Info($"IsSectionVisible: {viewModel.IsSectionVisible}");
        logger.Info($"CurrentSectionKey: {viewModel.CurrentSectionKey}");
    }

    private void OnClosed(object? sender, EventArgs e)
    {
        viewModel.PropertyChanged -= null;
        Loaded -= OnLoaded;
        Closed -= OnClosed;
    }

    // ── Frameless-window chrome ────────────────────────────────────────────
    // WindowStyle=None removes the native caption, so the nav bar provides
    // dragging, double-click maximise, and the three window buttons.

    private void OnChromeDrag(object sender, System.Windows.Input.MouseButtonEventArgs e)
    {
        if (e.ClickCount == 2)
        {
            ToggleMaximise();
            return;
        }

        if (e.ButtonState == System.Windows.Input.MouseButtonState.Pressed)
        {
            try { DragMove(); }
            catch (InvalidOperationException) { /* released mid-drag */ }
        }
    }

    private void OnToggleTheme(object sender, RoutedEventArgs e)
    {
        ThemeService.Toggle();
        UpdateThemeButton();
    }

    private void OnThemeButtonLoaded(object sender, RoutedEventArgs e) => UpdateThemeButton();

    // Sun offers light mode; moon offers dark mode (Segoe MDL2 glyphs).
    private void UpdateThemeButton()
    {
        ThemeToggleButton.Content = ThemeService.IsLight ? "\uE708" : "\uE706";
        ThemeToggleButton.ToolTip = ThemeService.IsLight ? "Switch to dark mode" : "Switch to light mode";
    }

    private void OnMinimize(object sender, RoutedEventArgs e) => WindowState = WindowState.Minimized;

    private void OnMaximize(object sender, RoutedEventArgs e) => ToggleMaximise();

    private void OnClose(object sender, RoutedEventArgs e) => Close();

    private void ToggleMaximise() =>
        WindowState = WindowState == WindowState.Maximized
            ? WindowState.Normal
            : WindowState.Maximized;

    // -- Maximise to the work area ----------------------------------------------
    // A WindowStyle=None window maximises over the whole monitor: it overhangs
    // every edge by the resize border and covers the taskbar. Answering
    // WM_GETMINMAXINFO with the monitor's work area keeps the maximised shell
    // exactly inside the visible desktop on whichever monitor it is on.

    private const int WM_GETMINMAXINFO = 0x0024;
    private const int MONITOR_DEFAULTTONEAREST = 2;

    protected override void OnSourceInitialized(EventArgs e)
    {
        base.OnSourceInitialized(e);
        if (System.Windows.Interop.HwndSource.FromHwnd(new System.Windows.Interop.WindowInteropHelper(this).Handle) is { } source)
        {
            source.AddHook(WndProc);
        }
    }

    private static IntPtr WndProc(IntPtr hwnd, int msg, IntPtr wParam, IntPtr lParam, ref bool handled)
    {
        if (msg != WM_GETMINMAXINFO)
        {
            return IntPtr.Zero;
        }

        var monitor = MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST);
        var info = new MONITORINFO { cbSize = System.Runtime.InteropServices.Marshal.SizeOf(typeof(MONITORINFO)) };
        if (monitor != IntPtr.Zero && GetMonitorInfo(monitor, ref info))
        {
            var mmi = (MINMAXINFO)System.Runtime.InteropServices.Marshal.PtrToStructure(lParam, typeof(MINMAXINFO))!;
            mmi.ptMaxPosition.X = info.rcWork.Left - info.rcMonitor.Left;
            mmi.ptMaxPosition.Y = info.rcWork.Top - info.rcMonitor.Top;
            mmi.ptMaxSize.X = info.rcWork.Right - info.rcWork.Left;
            mmi.ptMaxSize.Y = info.rcWork.Bottom - info.rcWork.Top;
            System.Runtime.InteropServices.Marshal.StructureToPtr(mmi, lParam, true);
        }

        return IntPtr.Zero;
    }

    [System.Runtime.InteropServices.DllImport("user32.dll")]
    private static extern IntPtr MonitorFromWindow(IntPtr hwnd, int flags);

    [System.Runtime.InteropServices.DllImport("user32.dll")]
    private static extern bool GetMonitorInfo(IntPtr monitor, ref MONITORINFO info);

    [System.Runtime.InteropServices.StructLayout(System.Runtime.InteropServices.LayoutKind.Sequential)]
    private struct POINT { public int X; public int Y; }

    [System.Runtime.InteropServices.StructLayout(System.Runtime.InteropServices.LayoutKind.Sequential)]
    private struct RECT { public int Left; public int Top; public int Right; public int Bottom; }

    [System.Runtime.InteropServices.StructLayout(System.Runtime.InteropServices.LayoutKind.Sequential)]
    private struct MINMAXINFO
    {
        public POINT ptReserved;
        public POINT ptMaxSize;
        public POINT ptMaxPosition;
        public POINT ptMinTrackSize;
        public POINT ptMaxTrackSize;
    }

    [System.Runtime.InteropServices.StructLayout(System.Runtime.InteropServices.LayoutKind.Sequential)]
    private struct MONITORINFO
    {
        public int cbSize;
        public RECT rcMonitor;
        public RECT rcWork;
        public int dwFlags;
    }
}
