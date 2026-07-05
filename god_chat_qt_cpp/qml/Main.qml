import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ApplicationWindow {
    id: window
    width: 420
    height: 760
    visible: true
    title: "God Chat"
    color: theme.background

    QtObject {
        id: theme
        property color background: "#101820"
        property color panel: "#17232e"
        property color input: "#223241"
        property color text: "#f5f7fb"
        property color muted: "#9fb0c3"
        property color own: "#29c7ac"
        property color other: "#f5f7fb"
        property color system: "#ffca6a"
    }

    ListModel {
        id: messageModel
    }

    Connections {
        target: chatClient

        function onMessageReceived(message, kind) {
            messageModel.append({ text: message, kind: kind })
            messageList.positionViewAtEnd()
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 16
        spacing: 12

        Label {
            text: "God Chat"
            color: theme.text
            font.pixelSize: 30
            font.bold: true
            Layout.fillWidth: true
        }

        Rectangle {
            color: theme.panel
            radius: 8
            Layout.fillWidth: true
            height: 184

            GridLayout {
                anchors.fill: parent
                anchors.margins: 12
                columns: 2
                rowSpacing: 8
                columnSpacing: 8

                Label { text: "Server"; color: theme.muted }
                TextField {
                    id: hostField
                    text: "192.168.1.10"
                    color: theme.text
                    placeholderText: "IP laptop server"
                    Layout.fillWidth: true
                }

                Label { text: "Port"; color: theme.muted }
                TextField {
                    id: portField
                    text: "5000"
                    color: theme.text
                    inputMethodHints: Qt.ImhDigitsOnly
                    Layout.fillWidth: true
                }

                Label { text: "Nama"; color: theme.muted }
                TextField {
                    id: usernameField
                    text: "Dhika"
                    color: theme.text
                    Layout.fillWidth: true
                }

                Button {
                    text: chatClient.connected ? "Disconnect" : "Connect"
                    Layout.columnSpan: 2
                    Layout.fillWidth: true
                    onClicked: {
                        if (chatClient.connected) {
                            chatClient.disconnectFromServer()
                        } else {
                            chatClient.connectToServer(hostField.text, Number(portField.text), usernameField.text)
                        }
                    }
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true

            Label {
                text: chatClient.status
                color: chatClient.connected ? theme.own : theme.system
                Layout.fillWidth: true
            }

            ComboBox {
                id: targetBox
                model: chatClient.users
                Layout.preferredWidth: 140
            }
        }

        ListView {
            id: messageList
            model: messageModel
            clip: true
            spacing: 8
            Layout.fillWidth: true
            Layout.fillHeight: true

            delegate: Rectangle {
                width: messageList.width
                implicitHeight: bubble.implicitHeight + 8
                color: "transparent"

                Label {
                    id: bubble
                    text: model.text
                    width: Math.min(parent.width * 0.82, implicitWidth + 28)
                    wrapMode: Text.Wrap
                    padding: 10
                    color: model.kind === "system" ? theme.system : (model.kind === "own" ? theme.own : theme.other)
                    background: Rectangle {
                        radius: 8
                        color: model.kind === "own" ? "#173d3b" : theme.panel
                    }
                    anchors.right: model.kind === "own" ? parent.right : undefined
                    anchors.left: model.kind === "own" ? undefined : parent.left
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 8

            TextField {
                id: messageField
                placeholderText: "Tulis pesan..."
                color: theme.text
                Layout.fillWidth: true
                onAccepted: sendButton.clicked()
            }

            Button {
                id: sendButton
                text: "Send"
                enabled: chatClient.connected
                onClicked: {
                    chatClient.sendMessage(targetBox.currentText, messageField.text)
                    messageField.text = ""
                }
            }
        }
    }
}
