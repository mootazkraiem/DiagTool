using System;
using Newtonsoft.Json.Linq;

namespace CANvision.Native.Services;

/// <summary>
/// The backend answered, but not with a result: the HTTP status and the backend's
/// reason (FastAPI "detail"), e.g. 409 when the selected model may not be used for
/// offline analysis, 400 for an unknown model id.
/// </summary>
public sealed class PythonApiException : Exception
{
    public PythonApiException(int statusCode, string detail)
        : base($"HTTP {statusCode}: {detail}")
    {
        StatusCode = statusCode;
        Detail = detail;
    }

    public int StatusCode { get; }
    public string Detail { get; }

    /// <summary>True for a deliberate refusal (bad request or conflict), not a server fault.</summary>
    public bool IsRefusal => StatusCode == 400 || StatusCode == 404 || StatusCode == 409;

    internal static string DetailFrom(string body)
    {
        if (string.IsNullOrWhiteSpace(body)) return "(no reason given)";
        try
        {
            var detail = JObject.Parse(body)["detail"];
            if (detail != null) return detail.Type == JTokenType.String ? detail.ToString() : detail.ToString(Newtonsoft.Json.Formatting.None);
        }
        catch (Newtonsoft.Json.JsonException)
        {
        }
        return body.Trim();
    }
}
