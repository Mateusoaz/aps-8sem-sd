FROM mcr.microsoft.com/dotnet/sdk:9.0 AS build
WORKDIR /src/api3/api

COPY PostgresStore.cs /src/PostgresStore.cs
COPY DomainStore.cs /src/DomainStore.cs
COPY api3/api/TransitoApi.csproj ./
RUN dotnet restore TransitoApi.csproj
COPY api3/api/ ./
RUN dotnet publish TransitoApi.csproj -c Release -o /app/publish --no-restore /p:UseAppHost=false

FROM mcr.microsoft.com/dotnet/aspnet:9.0-bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=build /app/publish ./
ENV PORT=3003
EXPOSE 3003
USER app
ENTRYPOINT ["dotnet", "TransitoApi.dll"]
