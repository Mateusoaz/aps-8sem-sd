using ThermalInversion.Api.Data;
using ThermalInversion.Api.Options;
using ThermalInversion.Api.Services;
using Microsoft.AspNetCore.Diagnostics.HealthChecks;
using Microsoft.EntityFrameworkCore;
using Microsoft.OpenApi.Models;

var builder = WebApplication.CreateBuilder(args);

// A connection string vem SOMENTE de variável de ambiente (ConnectionStrings__Default),
// definida no docker-compose.yml a partir do .env. Nenhuma credencial fica no código.
var connectionString = builder.Configuration.GetConnectionString("Default")
    ?? throw new InvalidOperationException(
        "Connection string 'Default' não configurada. Defina a variável de ambiente ConnectionStrings__Default.");

builder.Services.AddDbContext<ThermalInversionDbContext>(options => options
    .UseNpgsql(connectionString, npgsql => npgsql.EnableRetryOnFailure())
    .UseSnakeCaseNamingConvention());

builder.Services.Configure<AlertOptions>(builder.Configuration.GetSection(AlertOptions.SectionName));
builder.Services.AddScoped<AlertService>();

builder.Services.AddControllers();
builder.Services.AddEndpointsApiExplorer();
builder.Services.AddSwaggerGen();

// Health check do banco marcado como "ready": só é usado pelo endpoint de readiness
builder.Services.AddHealthChecks()
    .AddDbContextCheck<ThermalInversionDbContext>("postgres", tags: ["ready"]);

var app = builder.Build();

await DatabaseInitializer.InitializeAsync(app.Services, app.Logger);

// Prefixo do gateway: o Ingress encaminha /<prefixo>/... para este serviço (PATH_BASE vem do manifesto).
// O UsePathBase remove o prefixo antes de o roteamento escolher a rota.
var pathBase = Environment.GetEnvironmentVariable("PATH_BASE");
if (!string.IsNullOrEmpty(pathBase))
    app.UsePathBase(pathBase);
app.UseRouting();

// Evidência do balanceamento: toda resposta informa qual pod a atendeu e a versão da imagem.
var podName = Environment.MachineName;
var appVersion = Environment.GetEnvironmentVariable("APP_VERSION") ?? "dev";
app.Use(async (context, next) =>
{
    context.Response.Headers["X-Pod"] = podName;
    context.Response.Headers["X-Versao"] = appVersion;
    await next();
});

// Atrás do gateway, o Swagger precisa saber o prefixo para o "Try it out" chamar a URL certa.
app.UseSwagger(options => options.PreSerializeFilters.Add((document, request) =>
{
    if (request.PathBase.HasValue)
        document.Servers = [new OpenApiServer { Url = request.PathBase.Value }];
}));
app.UseSwaggerUI();

app.MapControllers();

// Liveness: "o processo está vivo?" — NÃO consulta dependências (banco, fila...).
// Se falhar, o orquestrador REINICIA o contêiner.
app.MapHealthChecks("/health/live", new HealthCheckOptions { Predicate = _ => false });

// Readiness: "estou apto a receber tráfego?" — verifica o banco.
// Se falhar, o orquestrador TIRA do balanceamento, sem reiniciar.
app.MapHealthChecks("/health/ready", new HealthCheckOptions { Predicate = check => check.Tags.Contains("ready") });

// Gasta CPU de propósito (n iterações), para acionar o HPA nos experimentos de escala.
app.MapGet("/processar", (int n = 1_000_000) =>
{
    n = Math.Clamp(n, 1, 50_000_000);
    double total = 0;
    for (var i = 1; i <= n; i++)
        total += Math.Sqrt(i);
    return Results.Ok(new { n, total, instancia = podName });
});

app.Run();
