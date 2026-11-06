using AirQuality.Api;
using AirQuality.Api.Data;
using AirQuality.Api.Infrastructure;
using AirQuality.Api.Options;
using AirQuality.Api.Services;
using Microsoft.AspNetCore.Diagnostics.HealthChecks;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Diagnostics.HealthChecks;

var builder = WebApplication.CreateBuilder(args);

// A connection string vem SOMENTE de variável de ambiente (ConnectionStrings__Default): no Compose,
// a partir do .env; no Kubernetes, montada no manifesto a partir do Secret. Nenhuma credencial no código.
var connectionString = builder.Configuration.GetConnectionString("Default")
    ?? throw new InvalidOperationException(
        "Connection string 'Default' não configurada. Defina a variável de ambiente ConnectionStrings__Default.");

builder.Services.AddDbContext<AirQualityDbContext>(options => options
    .UseNpgsql(connectionString, npgsql => npgsql.EnableRetryOnFailure())
    .UseSnakeCaseNamingConvention());

builder.Services.Configure<AlertOptions>(builder.Configuration.GetSection(AlertOptions.SectionName));
builder.Services.Configure<CacheOptions>(builder.Configuration.GetSection(CacheOptions.SectionName));
builder.Services.Configure<QueueOptions>(builder.Configuration.GetSection(QueueOptions.SectionName));
builder.Services.AddScoped<AlertService>();

// Banco criado em segundo plano: a API abre a porta na hora e só fica "pronta" quando o banco existir
builder.Services.AddSingleton<DatabaseStatus>();
builder.Services.AddHostedService<DatabaseInitializer>();

// Cache no Redis (ConnectionStrings__Redis) e fila no RabbitMQ (ConnectionStrings__RabbitMq).
// Sem as variáveis, a API funciona sozinha: sem cache e com o alerta avaliado dentro do POST.
builder.Services.AddSingleton<RedisConnection>();
builder.Services.AddSingleton<QueryCache>();
builder.Services.AddSingleton<ReadingQueue>();
builder.Services.AddHostedService<AlertConsumer>();

builder.Services.AddControllers();
builder.Services.AddEndpointsApiExplorer();
builder.Services.AddSwaggerGen();

// Checks marcados com "ready" só são usados pela readiness. Cada um tem 2 s para responder.
builder.Services.AddHealthChecks()
    .AddCheck<DatabaseHealthCheck>("banco", HealthStatus.Unhealthy, ["ready"], TimeSpan.FromSeconds(2))
    .AddCheck<CacheHealthCheck>("cache", HealthStatus.Degraded, ["ready"], TimeSpan.FromSeconds(2))
    .AddCheck<QueueHealthCheck>("fila", HealthStatus.Degraded, ["ready"], TimeSpan.FromSeconds(2));

var app = builder.Build();

// Evidência do balanceamento: TODA resposta diz qual pod atendeu e de qual versão da imagem.
app.Use(async (context, next) =>
{
    context.Response.Headers["X-Pod"] = AppInfo.Instance;
    context.Response.Headers["X-Versao"] = AppInfo.Version;
    await next();
});

// O Swagger fica embaixo do prefixo do serviço, para também ser alcançado pelo gateway:
//   http://localhost:8081/api/v1/air-quality/swagger (Kubernetes)  |  http://localhost:5001/api/v1/air-quality/swagger (Compose)
app.UseSwagger(options => options.RouteTemplate = ApiRoutes.Base + "/swagger/{documentName}/swagger.json");
app.UseSwaggerUI(options =>
{
    options.RoutePrefix = ApiRoutes.Base + "/swagger";
    options.SwaggerEndpoint("v1/swagger.json", ApiRoutes.ServiceName);
});

app.MapControllers();

// Liveness: "o processo está vivo?" — NÃO consulta dependências (banco, cache, fila).
// Se falhar, o kubelet REINICIA o contêiner.
var live = new HealthCheckOptions { Predicate = _ => false, ResponseWriter = HealthResponse.WriteAsync };
// Readiness: "posso receber tráfego agora?" — verifica banco, cache e fila a cada chamada.
// Se falhar (503), o pod SAI do Service, sem ser reiniciado.
var ready = new HealthCheckOptions { Predicate = c => c.Tags.Contains("ready"), ResponseWriter = HealthResponse.WriteAsync };

// /health/* é o que as probes chamam (direto no pod). As cópias sob o prefixo passam pelo gateway.
app.MapHealthChecks("/health/live", live);
app.MapHealthChecks("/health/ready", ready);
app.MapHealthChecks($"/{ApiRoutes.Base}/health/live", live);
app.MapHealthChecks($"/{ApiRoutes.Base}/health/ready", ready);

// Gasta CPU de propósito (n raízes quadradas), para acionar o HPA nos experimentos de escala.
app.MapGet($"/{ApiRoutes.Base}/cpu-work", (int n = 1_000_000) =>
{
    n = Math.Clamp(n, 1, 20_000_000);
    double total = 0;
    for (var i = 1; i <= n; i++)
        total += Math.Sqrt(i);
    return Results.Ok(new { n, total, instancia = AppInfo.Instance });
});

app.Run();
