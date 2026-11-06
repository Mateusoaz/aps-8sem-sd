namespace AirQuality.Api;

public static class ApiRoutes
{
    /// <summary>Nome do serviço: aparece no prefixo das rotas, nas chaves do cache e no nome da fila.</summary>
    public const string ServiceName = "air-quality";

    /// <summary>
    /// Prefixo de todas as rotas. Ele também é a regra do Ingress (/api/v1/air-quality -> este serviço),
    /// então o gateway encaminha a URL sem reescrever nada.
    /// </summary>
    public const string Base = "api/v1/" + ServiceName;
}
