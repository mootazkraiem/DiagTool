using System.Collections.Specialized;
using System.Windows;
using System.Windows.Controls;
using CANvision.Native.ViewModels;

namespace CANvision.Native.UI;

public partial class AnomalyIntelView : UserControl
{
    public AnomalyIntelView()
    {
        InitializeComponent();
        DataContextChanged += OnDataContextChanged;
    }

    private void OnDataContextChanged(object sender, DependencyPropertyChangedEventArgs e)
    {
        if (e.OldValue is AnomalyIntelViewModel oldVm)
            oldVm.ChatMessages.CollectionChanged -= OnChatMessagesChanged;
        if (e.NewValue is AnomalyIntelViewModel newVm)
            newVm.ChatMessages.CollectionChanged += OnChatMessagesChanged;
    }

    private void OnChatMessagesChanged(object? sender, NotifyCollectionChangedEventArgs e)
    {
        if (e.Action == NotifyCollectionChangedAction.Add)
            Dispatcher.BeginInvoke(System.Windows.Threading.DispatcherPriority.Background,
                new System.Action(() => ChatScrollViewer?.ScrollToEnd()));
    }
}
