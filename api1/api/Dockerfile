FROM mcr.microsoft.com/dotnet/sdk:9.0 AS build
WORKDIR /src/api1/api

COPY SharedApi.cs /src/SharedApi.cs
COPY api1/api/QualidadeArApi.csproj ./
RUN dotnet restore QualidadeArApi.csproj
COPY api1/api/ ./
RUN dotnet publish QualidadeArApi.csproj -c Release -o /app/publish --no-restore /p:UseAppHost=false

FROM mcr.microsoft.com/dotnet/aspnet:9.0-bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=build /app/publish ./
ENV PORT=3001
EXPOSE 3001
USER app
ENTRYPOINT ["dotnet", "QualidadeArApi.dll"]
