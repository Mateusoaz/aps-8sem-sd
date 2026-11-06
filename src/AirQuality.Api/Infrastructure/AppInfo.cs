namespace AirQuality.Api.Infrastructure;

/// <summary>Quem está respondendo: o nome do pod e a versão da imagem.</summary>
public static class AppInfo
{
    /// <summary>No Kubernetes o hostname do contêiner é o nome do pod (ex.: air-quality-api-6d9f-abcde).</summary>
    public static readonly string Instance = Environment.MachineName;

    /// <summary>Gravada na imagem pelo Dockerfile (--build-arg APP_VERSION=...).</summary>
    public static readonly string Version = Environment.GetEnvironmentVariable("APP_VERSION") ?? "dev";
}
