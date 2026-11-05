using Microsoft.EntityFrameworkCore;
using ThermalInversion.Api.Models;

namespace ThermalInversion.Api.Data;

// Com UseSnakeCaseNamingConvention() (Program.cs) as tabelas/colunas ficam no padrão do Postgres:
// TemperatureProfiles -> temperature_profiles, SurfaceTemperatureC -> surface_temperature_c
public class ThermalInversionDbContext(DbContextOptions<ThermalInversionDbContext> options) : DbContext(options)
{
    // Cada DbSet representa uma tabela que o EF Core consulta/grava neste banco lógico.
    public DbSet<TemperatureProfileReading> TemperatureProfiles => Set<TemperatureProfileReading>();
    public DbSet<SoilMoistureReading> SoilMoistureReadings => Set<SoilMoistureReading>();
    public DbSet<AirHumidityReading> AirHumidityReadings => Set<AirHumidityReading>();
    public DbSet<AtmosphericPressureReading> AtmosphericPressureReadings => Set<AtmosphericPressureReading>();
    public DbSet<WindSpeedReading> WindSpeedReadings => Set<WindSpeedReading>();
    public DbSet<Alert> Alerts => Set<Alert>();
}
