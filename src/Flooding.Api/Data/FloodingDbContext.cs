using Flooding.Api.Models;
using Microsoft.EntityFrameworkCore;

namespace Flooding.Api.Data;

// Com UseSnakeCaseNamingConvention() (Program.cs) as tabelas/colunas ficam no padrão do Postgres:
// WaterLevelReadings -> water_level_readings, MonitoringPointId -> monitoring_point_id
public class FloodingDbContext(DbContextOptions<FloodingDbContext> options) : DbContext(options)
{
    public DbSet<WaterLevelReading> WaterLevelReadings => Set<WaterLevelReading>();
    public DbSet<RainfallReading> RainfallReadings => Set<RainfallReading>();
    public DbSet<FlowRateReading> FlowRateReadings => Set<FlowRateReading>();
    public DbSet<Alert> Alerts => Set<Alert>();
}
