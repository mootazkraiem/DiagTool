using System.ComponentModel;
using System.Windows;
using System.Windows.Controls;
using CANvision.Native.ViewModels;

namespace CANvision.Native.UI;

public partial class HomeView : UserControl
{
    private HomeViewModel? hookedVm;

    public HomeView()
    {
        InitializeComponent();
        DataContextChanged += OnDataContextChanged;
    }

    private void OnDataContextChanged(object sender, DependencyPropertyChangedEventArgs e)
    {
        if (hookedVm is not null)
            hookedVm.PropertyChanged -= OnVmPropertyChanged;

        hookedVm = DataContext as HomeViewModel;

        if (hookedVm is not null)
            hookedVm.PropertyChanged += OnVmPropertyChanged;
    }

    private void OnVmPropertyChanged(object? sender, PropertyChangedEventArgs e)
    {
        if (e.PropertyName is not (nameof(HomeViewModel.IsLiveConnecting)
            or nameof(HomeViewModel.IsOfflineImporting)))
            return;

        var vm = hookedVm;
        if (vm is null) return;

        var state = vm.IsLiveConnecting  ? "LiveConnecting"
                  : vm.IsOfflineImporting ? "OfflineImporting"
                  : "ChooserMode";

        VisualStateManager.GoToElementState(RootGrid, state, useTransitions: true);
    }
}
