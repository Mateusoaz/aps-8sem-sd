FROM mcr.microsoft.com/dotnet/sdk:9.0 AS build
WORKDIR /src/api2/api

COPY SharedApi.cs /src/SharedApi.cs
COPY api2/api/AlagamentosApi.csproj ./
RUN dotnet restore AlagamentosApi.csproj
COPY api2/api/ ./
RUN dotnet publish AlagamentosApi.csproj -c Release -o /app/publish --no-restore /p:UseAppHost=false

FROM mcr.microsoft.com/dotnet/aspnet:9.0-bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=build /app/publish ./
ENV PORT=3002
EXPOSE 3002
USER app
ENTRYPOINT ["dotnet", "AlagamentosApi.dll"]
