using Flooding.Api;
using Flooding.Api.Data;
using Flooding.Api.Infrastructure;
using Flooding.Api.Options;
using Flooding.Api.Services;
using Microsoft.AspNetCore.Diagnostics.HealthChecks;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Diagnostics.HealthChecks;

var builder = WebApplication.CreateBuilder(args);

// A connection string vem SOMENTE de variável de ambiente (ConnectionStrings__Default): no Compose,
// a partir do .env; no Kubernetes, montada no manifesto a partir do Secret. Nenhuma credencial no código.
var connectionString = builder.Configuration.GetConnectionString("Default")
    ?? throw new InvalidOperationException(
        "Connection string 'Default' não configurada. Defina a variável de ambiente ConnectionStrings__Default.");

builder.Services.AddDbContext<FloodingDbContext>(options => options
    .UseNpgsql(connectionString, npgsql => npgsql.EnableRetryOnFailure())
    .UseSnakeCaseNamingConvention());

builder.Services.Configure<AlertOptions>(builder.Configuration.GetSection(AlertOptions.SectionName));
builder.Services.AddScoped<AlertService>();

// Banco criado em segundo plano: a API abre a porta na hora e só fica "pronta" quando o banco existir
builder.Services.AddSingleton<DatabaseStatus>();
builder.Services.AddHostedService<DatabaseInitializer>();

builder.Services.AddControllers();
builder.Services.AddEndpointsApiExplorer();
builder.Services.AddSwaggerGen();

// Só a readiness usa este check (tag "ready"). Ele tem 2 s para responder.
builder.Services.AddHealthChecks()
    .AddCheck<DatabaseHealthCheck>("banco", HealthStatus.Unhealthy, ["ready"], TimeSpan.FromSeconds(2));

var app = builder.Build();

// Prefixo do gateway. No cluster o Ingress manda /flooding/... para esta API sem reescrever a URL, e o
// manifesto define PATH_BASE=/flooding. O UsePathBase tira o prefixo antes de escolher a rota, então
// /flooding/api/v1/flooding/... chega no mesmo controller que /api/v1/flooding/...
// Sem a variável (Compose), nada muda.
var pathBase = app.Configuration["PATH_BASE"];
if (!string.IsNullOrEmpty(pathBase))
    app.UsePathBase(pathBase);
app.UseRouting();   // depois do UsePathBase, senão a rota é escolhida com o prefixo ainda na URL

// Evidência do balanceamento: TODA resposta diz qual pod atendeu e de qual versão da imagem.
app.Use(async (context, next) =>
{
    context.Response.Headers["X-Pod"] = AppInfo.Instance;
    context.Response.Headers["X-Versao"] = AppInfo.Version;
    await next();
});

// Swagger em /swagger: http://localhost:8081/flooding/swagger (cluster) | http://localhost:5002/swagger (Compose)
app.UseSwagger();
app.UseSwaggerUI(options => options.SwaggerEndpoint("v1/swagger.json", "Flooding.Api v1"));

app.MapControllers();

// Liveness: "o processo está vivo?". NÃO consulta o banco. Se falhar, o kubelet REINICIA o contêiner.
app.MapHealthChecks("/health/live", new HealthCheckOptions { Predicate = _ => false });
// Readiness: "posso receber requisições agora?". Consulta o banco a cada chamada.
// Se falhar (503), o pod SAI do Service, sem ser reiniciado.
app.MapHealthChecks("/health/ready", new HealthCheckOptions { Predicate = c => c.Tags.Contains("ready") });

// Gasta CPU de propósito (n raízes quadradas), para acionar o HPA nos experimentos de escala.
app.MapGet("/processar", (int n = 1_000_000) =>
{
    n = Math.Clamp(n, 1, 50_000_000);
    double resultado = 0;
    for (var i = 1; i <= n; i++)
        resultado += Math.Sqrt(i);
    return Results.Ok(new { n, resultado, pod = AppInfo.Instance });
});

app.Run();
