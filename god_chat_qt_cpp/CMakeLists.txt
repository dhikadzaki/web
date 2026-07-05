cmake_minimum_required(VERSION 3.21)

project(GodChatQtCpp VERSION 0.1 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(Qt6 REQUIRED COMPONENTS Core Quick Network)

qt_standard_project_setup(REQUIRES 6.5)

qt_add_executable(GodChatQtCpp
    src/ChatClient.cpp
    src/ChatClient.h
    src/main.cpp
)

qt_add_qml_module(GodChatQtCpp
    URI GodChat
    VERSION 1.0
    QML_FILES
        qml/Main.qml
)

target_link_libraries(GodChatQtCpp
    PRIVATE
        Qt6::Core
        Qt6::Quick
        Qt6::Network
)

set_target_properties(GodChatQtCpp PROPERTIES
    WIN32_EXECUTABLE TRUE
    MACOSX_BUNDLE TRUE
)
