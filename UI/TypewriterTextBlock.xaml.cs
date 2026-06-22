using System;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Documents;
using System.Windows.Media.Animation;
using System.Windows.Media;
using System.Windows.Threading;

namespace CANvision.Native.UI;

public partial class TypewriterTextBlock : UserControl
{
    public static readonly DependencyProperty TextProperty =
        DependencyProperty.Register(
            nameof(Text),
            typeof(string),
            typeof(TypewriterTextBlock),
            new PropertyMetadata(string.Empty, OnAnimationPropertyChanged));

    public static readonly DependencyProperty CharacterIntervalProperty =
        DependencyProperty.Register(
            nameof(CharacterInterval),
            typeof(int),
            typeof(TypewriterTextBlock),
            new PropertyMetadata(22, OnAnimationPropertyChanged));

    private readonly DispatcherTimer completionTimer;
    private readonly DispatcherTimer cursorTimer;
    private readonly DispatcherTimer typingTimer;
    private int currentIndex;

    public TypewriterTextBlock()
    {
        InitializeComponent();

        typingTimer = new DispatcherTimer();
        typingTimer.Tick += OnTypingTick;

        cursorTimer = new DispatcherTimer
        {
            Interval = TimeSpan.FromMilliseconds(340),
        };
        cursorTimer.Tick += OnCursorTick;

        completionTimer = new DispatcherTimer
        {
            Interval = TimeSpan.FromMilliseconds(360),
        };
        completionTimer.Tick += OnCompletionTick;

        Loaded += OnLoaded;
        Unloaded += OnUnloaded;
    }

    public string Text
    {
        get => (string)GetValue(TextProperty);
        set => SetValue(TextProperty, value);
    }

    public int CharacterInterval
    {
        get => (int)GetValue(CharacterIntervalProperty);
        set => SetValue(CharacterIntervalProperty, value);
    }

    private void OnLoaded(object sender, RoutedEventArgs e)
    {
        RestartAnimation();
    }

    private void OnUnloaded(object sender, RoutedEventArgs e)
    {
        typingTimer.Stop();
        cursorTimer.Stop();
        completionTimer.Stop();
    }

    private static void OnAnimationPropertyChanged(DependencyObject dependencyObject, DependencyPropertyChangedEventArgs e)
    {
        if (dependencyObject is TypewriterTextBlock control && control.IsLoaded)
        {
            control.RestartAnimation();
        }
    }

    private void RestartAnimation()
    {
        typingTimer.Stop();
        cursorTimer.Stop();
        completionTimer.Stop();
        CursorBrush.BeginAnimation(SolidColorBrush.OpacityProperty, null);

        currentIndex = 0;
        DisplayRun.Text = string.Empty;
        CursorRun.Text = "|";
        CursorBrush.Opacity = 1.0;

        var sourceText = Text ?? string.Empty;
        if (sourceText.Length == 0)
        {
            CursorRun.Text = string.Empty;
            return;
        }

        typingTimer.Interval = TimeSpan.FromMilliseconds(Math.Max(8, CharacterInterval));
        typingTimer.Start();
        cursorTimer.Start();
    }

    private void OnTypingTick(object? sender, EventArgs e)
    {
        var sourceText = Text ?? string.Empty;
        if (currentIndex >= sourceText.Length)
        {
            typingTimer.Stop();
            completionTimer.Start();
            return;
        }

        currentIndex++;
        DisplayRun.Text = sourceText.Substring(0, currentIndex);

        if (currentIndex >= sourceText.Length)
        {
            typingTimer.Stop();
            completionTimer.Start();
        }
    }

    private void OnCursorTick(object? sender, EventArgs e)
    {
        CursorBrush.Opacity = CursorBrush.Opacity > 0.5 ? 0.22 : 1.0;
    }

    private void OnCompletionTick(object? sender, EventArgs e)
    {
        completionTimer.Stop();
        cursorTimer.Stop();

        var fadeAnimation = new DoubleAnimation
        {
            From = CursorBrush.Opacity,
            To = 0.0,
            Duration = new Duration(TimeSpan.FromMilliseconds(220)),
            FillBehavior = FillBehavior.HoldEnd,
        };

        CursorBrush.BeginAnimation(SolidColorBrush.OpacityProperty, fadeAnimation);
    }
}
