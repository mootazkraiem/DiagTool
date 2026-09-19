using System;
using System.Globalization;
using System.Windows.Data;

namespace CANvision.Native.Converters
{
    /// <summary>
    /// Formats a UTC <see cref="DateTime"/> in local time.
    ///
    /// Runtime events carry UTC timestamps; every screen shows local time. Views
    /// that bind a raw event timestamp use this instead of a plain StringFormat,
    /// which would render the UTC value. ConverterParameter is the time format
    /// ("HH:mm:ss.fff" when omitted).
    /// </summary>
    public sealed class UtcToLocalTimeConverter : IValueConverter
    {
        public object Convert(object value, Type targetType, object parameter, CultureInfo culture)
        {
            if (value is not DateTime utc)
            {
                return string.Empty;
            }

            var format = parameter as string;
            if (string.IsNullOrWhiteSpace(format))
            {
                format = "HH:mm:ss.fff";
            }

            var local = utc.Kind == DateTimeKind.Utc ? utc.ToLocalTime() : utc;
            return local.ToString(format, CultureInfo.InvariantCulture);
        }

        public object ConvertBack(object value, Type targetType, object parameter, CultureInfo culture)
            => throw new NotSupportedException();
    }

    /// <summary>
    /// Turns a 0-100 percentage plus a pixel width into a pixel offset, so a playback
    /// cursor can sit over a chart that stretches with the window. Bind the percentage
    /// and the host element's ActualWidth, in that order. Pass ConverterParameter
    /// "fraction" when the value is 0-1.
    /// </summary>
    public sealed class PercentToOffsetConverter : IMultiValueConverter
    {
        public object Convert(object[] values, Type targetType, object parameter, CultureInfo culture)
        {
            if (values is null || values.Length < 2 ||
                values[0] is not double percent || values[1] is not double width || width <= 0)
            {
                return 0d;
            }

            // ConverterParameter "fraction": the value is 0-1 rather than 0-100.
            if (string.Equals(parameter as string, "fraction", StringComparison.OrdinalIgnoreCase))
            {
                percent *= 100.0;
            }

            var clamped = Math.Max(0, Math.Min(100, percent));
            return clamped / 100.0 * width;
        }

        public object[] ConvertBack(object value, Type[] targetTypes, object parameter, CultureInfo culture)
            => throw new NotSupportedException();
    }

    /// <summary>
    /// True when the bound values render as the same text. Used by DataTriggers that
    /// must compare a control's own tag against a view model readout (for example the
    /// active playback-speed chip), which a plain property Trigger cannot express.
    /// </summary>
    public sealed class EqualityConverter : IMultiValueConverter
    {
        public object Convert(object[] values, Type targetType, object parameter, CultureInfo culture)
        {
            if (values is null || values.Length < 2) return false;
            return string.Equals(values[0]?.ToString(), values[1]?.ToString(), StringComparison.OrdinalIgnoreCase);
        }

        public object[] ConvertBack(object value, Type[] targetTypes, object parameter, CultureInfo culture)
            => throw new NotSupportedException();
    }
}
