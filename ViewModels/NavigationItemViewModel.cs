namespace CANvision.Native.ViewModels;

public sealed class NavigationItemViewModel : ViewModelBase
{
    private bool isActive;
    private bool isUnlocked;

    public NavigationItemViewModel(string moduleCode, string title, string description, SectionViewModel section)
    {
        ModuleCode = moduleCode;
        Title = title;
        Description = description;
        Section = section;
    }

    public string ModuleCode { get; }

    public string Title { get; }

    public string Description { get; }

    public SectionViewModel Section { get; }

    public bool IsActive
    {
        get => isActive;
        set => SetProperty(ref isActive, value);
    }

    /// <summary>
    /// True only after analysis completes. Controls tab enabled state and navigation guard.
    /// </summary>
    public bool IsUnlocked
    {
        get => isUnlocked;
        set => SetProperty(ref isUnlocked, value);
    }
}
