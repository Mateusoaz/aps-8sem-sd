namespace Flooding.Api.Options;

/// <summary>Limites das regras de alerta. Sobrescritos por variáveis de ambiente (Alerts__OverflowLevelCm).</summary>
public class AlertOptions
{
    public const string SectionName = "Alerts";

    /// <summary>Cota de transbordamento: nível da água (cm) a partir do qual o córrego transborda.</summary>
    public double OverflowLevelCm { get; set; } = 300;
}
