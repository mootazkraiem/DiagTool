using System;
using System.IO;
using System.Text;

namespace CANvision.Native.Services;

public sealed class AppLogger
{
    private readonly object sync = new();

    public AppLogger()
    {
        var logDirectory = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "logs");
        Directory.CreateDirectory(logDirectory);
        LogFilePath = Path.Combine(logDirectory, "canvision-native.log");
    }

    public string LogFilePath { get; }

    public void Info(string message) => Write("INFO", message);

    public void Error(string message, Exception? exception = null)
    {
        var builder = new StringBuilder(message);
        if (exception is not null)
        {
            builder.AppendLine();
            builder.Append(exception);
        }

        Write("ERROR", builder.ToString());
    }

    private void Write(string level, string message)
    {
        var line = $"[{DateTime.Now:yyyy-MM-dd HH:mm:ss.fff}] [{level}] {message}";
        Console.WriteLine(line);

        lock (sync)
        {
            File.AppendAllText(LogFilePath, line + Environment.NewLine);
        }
    }
}
