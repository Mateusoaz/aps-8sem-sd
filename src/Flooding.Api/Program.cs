using Flooding.Api.Data;
using Flooding.Api.Options;
using Flooding.Api.Services;
using Microsoft.AspNetCore.Diagnostics.HealthChecks;
using Microsoft.EntityFrameworkCore;

var builder = WebApplication.CreateBuilder(args);

// 1) Lê a configuração por prioridade: variáveis de ambiente, arquivos JSON e valores padrão.
// A connection string vem SOMENTE de variável de ambiente (ConnectionStrings__Default),
// definida no docker-compose.yml a partir do .env. Nenhuma credencial fica no código.
var connectionString = builder.Configuration.GetConnectionString("Default")
    ?? throw new InvalidOperationException(
        "Connection string 'Default' não configurada. Defina a variável de ambiente ConnectionStrings__Default.");

// 2) Registra o DbContext por requisição. EF Core traduz LINQ em SQL para PostgreSQL.
builder.Services.AddDbContext<FloodingDbContext>(options => options
    .UseNpgsql(connectionString, npgsql => npgsql.EnableRetryOnFailure())
    .UseSnakeCaseNamingConvention());

// 3) Injeta os limites dos alertas e o serviço que aplica a regra de negócio.
builder.Services.Configure<AlertOptions>(builder.Configuration.GetSection(AlertOptions.SectionName));
builder.Services.AddScoped<AlertService>();

builder.Services.AddControllers();
builder.Services.AddEndpointsApiExplorer();
builder.Services.AddSwaggerGen();
if (builder.Configuration.GetValue<bool>("CACHE_ENABLED"))
{
    // Quando habilitado, todas as réplicas compartilham respostas cacheadas no Redis.
    var redisConnection = builder.Configuration.GetConnectionString("Redis")
        ?? throw new InvalidOperationException("CACHE_ENABLED requer ConnectionStrings__Redis.");
    builder.Services.AddStackExchangeRedisOutputCache(options =>
    {
        options.Configuration = redisConnection;
        options.InstanceName = "aps-flooding-";
    });
}
builder.Services.AddOutputCache();

// Liveness verifica o processo; readiness inclui este health check do PostgreSQL.
builder.Services.AddHealthChecks()
    .AddDbContextCheck<FloodingDbContext>("postgres", tags: ["ready"]);

var app = builder.Build();

// Garante que o banco/tabelas existam antes de começar a atender requisições.
await DatabaseInitializer.InitializeAsync(app.Services, app.Logger);

// Middleware HTTP: os pedidos atravessam esta função antes do controller; OnStarting
// carimba também as respostas de erro e respostas servidas pelo cache.
app.Use(async (context, next) =>
{
    context.Response.OnStarting(() =>
    {
        context.Response.Headers["X-Pod"] = Environment.GetEnvironmentVariable("HOSTNAME") ?? Environment.MachineName;
        context.Response.Headers["X-Versao"] = builder.Configuration["APP_VERSION"] ?? "1.0.0";
        return Task.CompletedTask;
    });
    await next();
});

app.UseSwagger();
app.UseSwaggerUI();
// O middleware só participa do pipeline quando a opção está ligada.
if (builder.Configuration.GetValue<bool>("CACHE_ENABLED")) app.UseOutputCache();

app.MapControllers();

// Liveness: "o processo está vivo?" — NÃO consulta dependências (banco, fila...).
// Se falhar, o orquestrador REINICIA o contêiner.
app.MapHealthChecks("/health/live", new HealthCheckOptions { Predicate = _ => false });

// Readiness: "estou apto a receber tráfego?" — verifica o banco.
// Se falhar, o orquestrador TIRA do balanceamento, sem reiniciar.
app.MapHealthChecks("/health/ready", new HealthCheckOptions { Predicate = check => check.Tags.Contains("ready") });

app.Run();
