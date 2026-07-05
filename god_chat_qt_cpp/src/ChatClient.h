#pragma once

#include <QObject>
#include <QTcpSocket>
#include <QStringList>

class ChatClient : public QObject
{
    Q_OBJECT
    Q_PROPERTY(bool connected READ connected NOTIFY connectedChanged)
    Q_PROPERTY(QString status READ status NOTIFY statusChanged)
    Q_PROPERTY(QStringList users READ users NOTIFY usersChanged)

public:
    explicit ChatClient(QObject *parent = nullptr);

    bool connected() const;
    QString status() const;
    QStringList users() const;

    Q_INVOKABLE void connectToServer(const QString &host, int port, const QString &username);
    Q_INVOKABLE void disconnectFromServer();
    Q_INVOKABLE void sendMessage(const QString &target, const QString &message);

signals:
    void connectedChanged();
    void statusChanged();
    void usersChanged();
    void messageReceived(const QString &message, const QString &kind);

private slots:
    void handleConnected();
    void handleDisconnected();
    void handleReadyRead();
    void handleError(QAbstractSocket::SocketError error);

private:
    void setConnected(bool connected);
    void setStatus(const QString &status);
    void handleIncomingLine(const QString &line);
    void updateUsers(const QString &payload);

    QTcpSocket m_socket;
    bool m_connected = false;
    QString m_status = "Belum connect";
    QString m_username;
    QStringList m_users = {"All"};
};
