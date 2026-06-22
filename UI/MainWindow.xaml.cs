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
        WindowStyle = WindowStyle.SingleBorderWindow;
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
}
