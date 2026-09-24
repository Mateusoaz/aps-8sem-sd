namespace AirQuality.Api.Options;

/// <summary>Limites das regras de alerta. Sobrescritos por variáveis de ambiente (Alerts__Pm25Limit, ...).</summary>
public class AlertOptions
{
    public const string SectionName = "Alerts";

    /// <summary>Limite de PM2.5 em µg/m³.</summary>
    public double Pm25Limit { get; set; } = 25;

    /// <summary>Quantas leituras seguidas acima do limite disparam o alerta.</summary>
    public int Pm25ConsecutiveReadings { get; set; } = 3;
}
