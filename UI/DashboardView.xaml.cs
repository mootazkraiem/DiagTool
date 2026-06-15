using System.Windows.Controls;
using CANvision.Native.ViewModels;

namespace CANvision.Native.UI;

public partial class DashboardView : UserControl
{
    public DashboardView()
    {
        InitializeComponent();
        DataContextChanged += (_, args) =>
        {
            if (args.OldValue is DashboardViewModel old)
                old.PropertyChanged -= OnVmPropertyChanged;
            if (args.NewValue is DashboardViewModel vm)
                vm.PropertyChanged += OnVmPropertyChanged;
        };
        Loaded += (_, _) =>
        {
            if (DataContext is DashboardViewModel vm)
                vm.PropertyChanged += OnVmPropertyChanged;
        };
        Unloaded += (_, _) =>
        {
            if (DataContext is DashboardViewModel vm)
                vm.PropertyChanged -= OnVmPropertyChanged;
        };
    }

    private void OnVmPropertyChanged(object? sender, System.ComponentModel.PropertyChangedEventArgs e)
    {
        // Intentionally minimal — XAML bindings handle all display updates.
    }
}
