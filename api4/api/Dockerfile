FROM mcr.microsoft.com/dotnet/sdk:9.0 AS build
WORKDIR /src/api4/api

COPY SharedApi.cs /src/SharedApi.cs
COPY api4/api/InversaoTermicaApi.csproj ./
RUN dotnet restore InversaoTermicaApi.csproj
COPY api4/api/ ./
RUN dotnet publish InversaoTermicaApi.csproj -c Release -o /app/publish --no-restore /p:UseAppHost=false

FROM mcr.microsoft.com/dotnet/aspnet:9.0-bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=build /app/publish ./
ENV PORT=3003
EXPOSE 3003
USER app
ENTRYPOINT ["dotnet", "InversaoTermicaApi.dll"]
