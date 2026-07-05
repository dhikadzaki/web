#include <QGuiApplication>
#include <QQmlApplicationEngine>
#include <QQmlContext>

#include "ChatClient.h"

int main(int argc, char *argv[])
{
    QGuiApplication app(argc, argv);

    ChatClient chatClient;

    QQmlApplicationEngine engine;
    engine.rootContext()->setContextProperty("chatClient", &chatClient);
    engine.loadFromModule("GodChat", "Main");

    if (engine.rootObjects().isEmpty()) {
        return -1;
    }

    return app.exec();
}
