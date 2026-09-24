using Flooding.Api.Data;
using Flooding.Api.Options;
using Flooding.Api.Services;
using Microsoft.AspNetCore.Diagnostics.HealthChecks;
using Microsoft.EntityFrameworkCore;

var builder = WebApplication.CreateBuilder(args);

// A connection string vem SOMENTE de variável de ambiente (ConnectionStrings__Default),
// definida no docker-compose.yml a partir do .env. Nenhuma credencial fica no código.
var connectionString = builder.Configuration.GetConnectionString("Default")
    ?? throw new InvalidOperationException(
        "Connection string 'Default' não configurada. Defina a variável de ambiente ConnectionStrings__Default.");

builder.Services.AddDbContext<FloodingDbContext>(options => options
    .UseNpgsql(connectionString, npgsql => npgsql.EnableRetryOnFailure())
    .UseSnakeCaseNamingConvention());

builder.Services.Configure<AlertOptions>(builder.Configuration.GetSection(AlertOptions.SectionName));
builder.Services.AddScoped<AlertService>();

builder.Services.AddControllers();
builder.Services.AddEndpointsApiExplorer();
builder.Services.AddSwaggerGen();

// Health check do banco marcado como "ready": só é usado pelo endpoint de readiness
builder.Services.AddHealthChecks()
    .AddDbContextCheck<FloodingDbContext>("postgres", tags: ["ready"]);

var app = builder.Build();

await DatabaseInitializer.InitializeAsync(app.Services, app.Logger);

app.UseSwagger();
app.UseSwaggerUI();

app.MapControllers();

// Liveness: "o processo está vivo?" — NÃO consulta dependências (banco, fila...).
// Se falhar, o orquestrador REINICIA o contêiner.
app.MapHealthChecks("/health/live", new HealthCheckOptions { Predicate = _ => false });

// Readiness: "estou apto a receber tráfego?" — verifica o banco.
// Se falhar, o orquestrador TIRA do balanceamento, sem reiniciar.
app.MapHealthChecks("/health/ready", new HealthCheckOptions { Predicate = check => check.Tags.Contains("ready") });

app.Run();
