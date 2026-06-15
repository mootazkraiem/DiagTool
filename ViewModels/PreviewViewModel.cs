using System;
using System.Collections.Generic;
using System.Linq;
using System.Windows.Threading;
using CANvision.Native.Models;
using CANvision.Native.Services;
using CommunityToolkit.Mvvm.Input;

namespace CANvision.Native.ViewModels;

public sealed class PreviewDotItem : ViewModelBase
{
    private bool _isActive;

    public PreviewDotItem(SectionKey key, string title)
    {
        Key = key;
        Title = title;
    }

    public SectionKey Key { get; }

    public string Title { get; }

    public bool IsActive
    {
        get => _isActive;
        set
        {
            _isActive = value;
            OnPropertyChanged();
        }
    }
}

public sealed partial class PreviewViewModel : ViewModelBase
{
    private readonly IRelayCommand navigateHomeFallbackCommand;
    private NavigationService? navigationService;

    private DispatcherTimer? typeTimer;
    private DispatcherTimer clockTimer;

    private SectionKey activeKey;
    private string fullTitle = string.Empty;
    private string fullDescription = string.Empty;
    private string fullButtonLabel = string.Empty;

    private readonly string fullLabel = "TACTICAL VEHICLE BRIEF";
    private readonly string fullStatus = "LOCAL FALLBACK | SOURCE JSON FALLBACK | LAST SYNC 15:30:00";

    private string[] labelWords = Array.Empty<string>();
    private string[] titleWords = Array.Empty<string>();
    private string[] descriptionWords = Array.Empty<string>();
    private string[] statusWords = Array.Empty<string>();
    private string[] buttonWords = Array.Empty<string>();

    private int labelWordIndex;
    private int titleWordIndex;
    private int descriptionWordIndex;
    private int statusWordIndex;
    private int buttonWordIndex;

    private string displayLabel = string.Empty;
    private string displayDescription = string.Empty;
    private string displayTitle = string.Empty;
    private string displayStatus = string.Empty;
    private string displayButtonLabel = string.Empty;
    private string currentTimeText = string.Empty;

    public PreviewViewModel(NavigationService? navigationService)
    {
        this.navigationService = navigationService;
        LaunchSectionCommand = new RelayCommand(ExecuteLaunchSection);
        ChangePreviewCommand = new RelayCommand<SectionKey>(ExecuteChangePreview);
        navigateHomeFallbackCommand = new RelayCommand(() => { });

        clockTimer = new DispatcherTimer { Interval = TimeSpan.FromSeconds(1) };
        clockTimer.Tick += (_, _) => { CurrentTimeText = DateTime.UtcNow.ToString("HH:mm:ss UTC"); };
        clockTimer.Start();
        CurrentTimeText = DateTime.UtcNow.ToString("HH:mm:ss UTC");

        foreach (var desc in SectionCatalog.All)
        {
            Dots.Add(new PreviewDotItem(desc.Key, desc.Title));
        }

        ActiveKey = SectionCatalog.All.First().Key;
    }

    public System.Collections.ObjectModel.ObservableCollection<PreviewDotItem> Dots { get; } = new();

    public IRelayCommand NavigateHomeCommand => navigationService?.NavigateToGarageCommand ?? navigateHomeFallbackCommand;

    public IRelayCommand LaunchSectionCommand { get; }

    public IRelayCommand<SectionKey> ChangePreviewCommand { get; }

    public SectionKey ActiveKey
    {
        get => activeKey;
        set
        {
            if (activeKey == value)
            {
                return;
            }

            activeKey = value;
            OnPropertyChanged();

            foreach (var dot in Dots)
            {
                dot.IsActive = dot.Key == activeKey;
            }

            var catalog = SectionCatalog.For(value);
            if (catalog is not null) StartTypewriter(catalog.Title, catalog.BriefingDescription);
        }
    }

    public string DisplayLabel
    {
        get => displayLabel;
        set
        {
            displayLabel = value;
            OnPropertyChanged();
        }
    }

    public string DisplayDescription
    {
        get => displayDescription;
        set
        {
            displayDescription = value;
            OnPropertyChanged();
        }
    }

    public string DisplayTitle
    {
        get => displayTitle;
        set
        {
            displayTitle = value;
            OnPropertyChanged();
        }
    }

    public string DisplayStatus
    {
        get => displayStatus;
        set
        {
            displayStatus = value;
            OnPropertyChanged();
        }
    }

    public string DisplayButtonLabel
    {
        get => displayButtonLabel;
        set
        {
            displayButtonLabel = value;
            OnPropertyChanged();
        }
    }

    public string CurrentTimeText
    {
        get => currentTimeText;
        set
        {
            currentTimeText = value;
            OnPropertyChanged();
        }
    }

    public void AttachNavigationService(NavigationService navigation)
    {
        navigationService = navigation;
        OnPropertyChanged(nameof(NavigateHomeCommand));
    }

    public void SelectPrevious()
    {
        var keys = SectionCatalog.All.Select(s => s.Key).ToList();
        var idx = keys.IndexOf(activeKey);
        idx = (idx - 1 + keys.Count) % keys.Count;
        ActiveKey = keys[idx];
    }

    public void SelectNext()
    {
        var keys = SectionCatalog.All.Select(s => s.Key).ToList();
        var idx = keys.IndexOf(activeKey);
        idx = (idx + 1) % keys.Count;
        ActiveKey = keys[idx];
    }

    private void ExecuteLaunchSection()
    {
        navigationService?.NavigateToSectionCommand.Execute(activeKey);
    }

    private void ExecuteChangePreview(SectionKey key)
    {
        ActiveKey = key;
    }

    public void StartTypewriter(string title, string description)
    {
        fullTitle = title;
        fullDescription = description;
        fullButtonLabel = $"ENTER {title.ToUpperInvariant()} >";

        labelWords = SplitWords(fullLabel);
        titleWords = SplitWords(fullTitle);
        descriptionWords = SplitWords(fullDescription);
        statusWords = SplitWords(fullStatus);
        buttonWords = SplitWords(fullButtonLabel);

        labelWordIndex = 0;
        titleWordIndex = 0;
        descriptionWordIndex = 0;
        statusWordIndex = 0;
        buttonWordIndex = 0;

        DisplayLabel = string.Empty;
        DisplayTitle = string.Empty;
        DisplayDescription = string.Empty;
        DisplayStatus = string.Empty;
        DisplayButtonLabel = string.Empty;

        typeTimer?.Stop();
        typeTimer = new DispatcherTimer
        {
            Interval = TimeSpan.FromMilliseconds(60),
        };

        typeTimer.Tick += (_, _) =>
        {
            if (TryAdvanceWords(labelWords, ref labelWordIndex, value => DisplayLabel = value)) return;
            if (TryAdvanceWords(titleWords, ref titleWordIndex, value => DisplayTitle = value)) return;
            if (TryAdvanceWords(descriptionWords, ref descriptionWordIndex, value => DisplayDescription = value)) return;
            if (TryAdvanceWords(statusWords, ref statusWordIndex, value => DisplayStatus = value)) return;
            if (TryAdvanceWords(buttonWords, ref buttonWordIndex, value => DisplayButtonLabel = value)) return;

            typeTimer?.Stop();
        };

        typeTimer.Start();
    }

    private static string[] SplitWords(string value)
    {
        return value.Split(new[] { ' ' }, StringSplitOptions.RemoveEmptyEntries);
    }

    private static bool TryAdvanceWords(IReadOnlyList<string> words, ref int index, Action<string> assign)
    {
        if (index >= words.Count)
        {
            return false;
        }

        index++;
        assign(string.Join(" ", words.Take(index)));
        return true;
    }
}
