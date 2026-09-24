using AirQuality.Api.Models;
using Microsoft.EntityFrameworkCore;

namespace AirQuality.Api.Data;

// Com UseSnakeCaseNamingConvention() (Program.cs) as tabelas/colunas ficam no padrão do Postgres:
// ParticulateReadings -> particulate_readings, StationId -> station_id
public class AirQualityDbContext(DbContextOptions<AirQualityDbContext> options) : DbContext(options)
{
    public DbSet<ParticulateReading> ParticulateReadings => Set<ParticulateReading>();
    public DbSet<GasReading> GasReadings => Set<GasReading>();
    public DbSet<EnvironmentReading> EnvironmentReadings => Set<EnvironmentReading>();
    public DbSet<Alert> Alerts => Set<Alert>();
}
