# ============ Estágio 1: build (tem o SDK completo, ~800 MB) ============
FROM mcr.microsoft.com/dotnet/sdk:8.0 AS build
WORKDIR /src

# Regra de ouro do cache: copia SÓ o .csproj e restaura os pacotes primeiro.
# Enquanto o .csproj não mudar, o Docker reaproveita esta camada e não baixa os pacotes de novo.
COPY Flooding.Api.csproj ./
RUN dotnet restore

# Agora sim copia o código-fonte (muda sempre) e publica
COPY . ./
RUN dotnet publish -c Release -o /app/publish --no-restore /p:UseAppHost=false

# ============ Estágio 2: runtime (só o necessário para RODAR, ~110 MB) ============
FROM mcr.microsoft.com/dotnet/aspnet:8.0-alpine AS final
WORKDIR /app

# Do estágio de build só levamos as DLLs publicadas — nada de SDK nem código-fonte
COPY --from=build /app/publish ./

# Usuário não-root que já vem na imagem oficial do .NET 8 (UID 1654)
USER $APP_UID

# As imagens .NET 8 escutam na porta 8080 por padrão
EXPOSE 8080
ENTRYPOINT ["dotnet", "Flooding.Api.dll"]
