using AirQuality.Api.Dtos;
using AirQuality.Api.Models;

namespace AirQuality.Api.Data;

public static class QueryExtensions
{
    /// <summary>Filtra pelo período (from/to) e devolve as mais recentes primeiro, até o limite.</summary>
    public static IQueryable<T> InPeriod<T>(this IQueryable<T> query, PeriodQuery period) where T : IReading
    {
        if (period.From is not null)
            query = query.Where(r => r.Timestamp >= period.From);
        if (period.To is not null)
            query = query.Where(r => r.Timestamp <= period.To);

        return query.OrderByDescending(r => r.Timestamp).Take(period.Limit);
    }
}
