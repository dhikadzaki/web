#include "ChatClient.h"

namespace {
constexpr auto UserListPrefix = "::USERLIST::";
}

ChatClient::ChatClient(QObject *parent)
    : QObject(parent)
{
    connect(&m_socket, &QTcpSocket::connected, this, &ChatClient::handleConnected);
    connect(&m_socket, &QTcpSocket::disconnected, this, &ChatClient::handleDisconnected);
    connect(&m_socket, &QTcpSocket::readyRead, this, &ChatClient::handleReadyRead);
    connect(&m_socket, &QTcpSocket::errorOccurred, this, &ChatClient::handleError);
}

bool ChatClient::connected() const
{
    return m_connected;
}

QString ChatClient::status() const
{
    return m_status;
}

QStringList ChatClient::users() const
{
    return m_users;
}

void ChatClient::connectToServer(const QString &host, int port, const QString &username)
{
    if (m_connected || host.trimmed().isEmpty() || username.trimmed().isEmpty()) {
        return;
    }

    m_username = username.trimmed();
    setStatus("Menghubungkan...");
    m_socket.connectToHost(host.trimmed(), port);
}

void ChatClient::disconnectFromServer()
{
    if (m_socket.state() == QAbstractSocket::ConnectedState) {
        m_socket.write("/quit\n");
        m_socket.flush();
    }

    m_socket.disconnectFromHost();
}

void ChatClient::sendMessage(const QString &target, const QString &message)
{
    const QString cleanMessage = message.trimmed();
    if (!m_connected || cleanMessage.isEmpty()) {
        return;
    }

    if (target != "All" && !target.trimmed().isEmpty()) {
        m_socket.write(QString("/pm %1 %2\n").arg(target, cleanMessage).toUtf8());
    } else {
        m_socket.write(QString("%1\n").arg(cleanMessage).toUtf8());
        emit messageReceived(QString("Kamu: %1").arg(cleanMessage), "own");
    }
}

void ChatClient::handleConnected()
{
    setConnected(true);
    setStatus(QString("Connect sebagai %1").arg(m_username));
    emit messageReceived("[CLIENT] Terhubung ke server.", "system");
    m_socket.write(QString("%1\n").arg(m_username).toUtf8());
}

void ChatClient::handleDisconnected()
{
    setConnected(false);
    setStatus("Belum connect");
    m_users = {"All"};
    emit usersChanged();
    emit messageReceived("[CLIENT] Disconnect.", "system");
}

void ChatClient::handleReadyRead()
{
    const QString text = QString::fromUtf8(m_socket.readAll());
    const QStringList lines = text.split('\n', Qt::SkipEmptyParts);

    for (const QString &line : lines) {
        handleIncomingLine(line.trimmed());
    }
}

void ChatClient::handleError(QAbstractSocket::SocketError error)
{
    Q_UNUSED(error)
    setStatus(QString("Error: %1").arg(m_socket.errorString()));
}

void ChatClient::setConnected(bool connected)
{
    if (m_connected == connected) {
        return;
    }

    m_connected = connected;
    emit connectedChanged();
}

void ChatClient::setStatus(const QString &status)
{
    if (m_status == status) {
        return;
    }

    m_status = status;
    emit statusChanged();
}

void ChatClient::handleIncomingLine(const QString &line)
{
    if (line.isEmpty()) {
        return;
    }

    if (line.startsWith(UserListPrefix)) {
        updateUsers(line.mid(QString(UserListPrefix).size()));
        return;
    }

    const QString kind = line.startsWith("[SERVER]") || line.startsWith("[CLIENT]")
        ? "system"
        : "other";
    emit messageReceived(line, kind);
}

void ChatClient::updateUsers(const QString &payload)
{
    QStringList nextUsers = {"All"};
    const QStringList names = payload.split('|', Qt::SkipEmptyParts);

    for (const QString &name : names) {
        const QString cleanName = name.trimmed();
        if (!cleanName.isEmpty() && cleanName != m_username) {
            nextUsers.append(cleanName);
        }
    }

    m_users = nextUsers;
    emit usersChanged();
}
