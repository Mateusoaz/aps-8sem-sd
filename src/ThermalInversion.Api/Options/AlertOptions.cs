namespace ThermalInversion.Api.Options;

/// <summary>Limites das regras de alerta. Sobrescritos por variáveis de ambiente (Alerts__MinInversionGradientC).</summary>
public class AlertOptions
{
    public const string SectionName = "Alerts";

    /// <summary>
    /// Há inversão quando (temp. superior - temp. superfície) é MAIOR que este valor (°C).
    /// Com 0, qualquer camada superior mais quente que a superfície já conta como inversão.
    /// </summary>
    public double MinInversionGradientC { get; set; } = 0;
}
