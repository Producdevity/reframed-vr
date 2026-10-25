cmake_minimum_required(VERSION 3.22)
project(reframed-vr LANGUAGES C CXX)
find_package(OpenXR REQUIRED)
find_package(Vulkan REQUIRED)
find_package(Threads REQUIRED)
add_library(openxr-procaddr SHARED src/openxr-procaddr.c)
target_compile_features(openxr-procaddr PRIVATE c_std_11)
target_compile_options(openxr-procaddr PRIVATE -Wall -Wextra -Werror)
target_link_libraries(openxr-procaddr PRIVATE OpenXR::openxr_loader Vulkan::Vulkan Threads::Threads ${CMAKE_DL_LIBS})
install(TARGETS openxr-procaddr LIBRARY DESTINATION libexec/reframed-vr)
add_executable(xr-probe src/xr-probe.cpp src/xr-renderer.cpp)
target_compile_features(xr-probe PRIVATE cxx_std_17)
target_compile_options(xr-probe PRIVATE -Wall -Wextra -Werror -Wno-missing-field-initializers)
target_link_libraries(xr-probe PRIVATE OpenXR::openxr_loader Vulkan::Vulkan)
install(TARGETS xr-probe RUNTIME DESTINATION bin)
add_executable(vulkan-interop src/vulkan-interop.c)
target_compile_features(vulkan-interop PRIVATE c_std_11)
target_compile_options(vulkan-interop PRIVATE -Wall -Wextra -Werror)
target_link_libraries(vulkan-interop PRIVATE Vulkan::Vulkan)
install(TARGETS vulkan-interop RUNTIME DESTINATION bin)

option(REFRAMED_PICO_DISPLAY_HANDOFF "Build the native Pico inherited-mode handoff" OFF)
if(REFRAMED_PICO_DISPLAY_HANDOFF)
    if(NOT CMAKE_SYSTEM_NAME STREQUAL "Linux")
        message(FATAL_ERROR "Pico display handoff requires Linux")
    endif()
    find_package(PkgConfig REQUIRED)
    pkg_check_modules(DRM REQUIRED IMPORTED_TARGET libdrm)
    add_executable(pico-display-handoff src/pico-display-handoff.c)
    target_compile_features(pico-display-handoff PRIVATE c_std_11)
    target_compile_options(pico-display-handoff PRIVATE -Wall -Wextra -Werror)
    target_link_libraries(pico-display-handoff PRIVATE PkgConfig::DRM)
    install(TARGETS pico-display-handoff RUNTIME DESTINATION libexec/reframed-vr
            COMPONENT PicoDisplayHandoff)
    configure_file(system/pico/reframed-pico-display-handoff.service.in
                   reframed-pico-display-handoff.service @ONLY)
    install(FILES "${CMAKE_CURRENT_BINARY_DIR}/reframed-pico-display-handoff.service"
            DESTINATION lib/systemd/system COMPONENT PicoDisplayHandoff)
    install(FILES system/pico/70-reframed-pico-display.rules
            DESTINATION lib/udev/rules.d COMPONENT PicoDisplayHandoff)
endif()

option(REFRAMED_PICO_WIFI_IDENTITY "Install native Pico Wi-Fi identity startup" OFF)
if(REFRAMED_PICO_WIFI_IDENTITY)
    if(NOT CMAKE_SYSTEM_NAME STREQUAL "Linux")
        message(FATAL_ERROR "Pico Wi-Fi identity startup requires Linux")
    endif()
    install(PROGRAMS tools/pico-wifi-identity.py DESTINATION libexec/reframed-vr
            COMPONENT PicoWifiIdentity)
    install(FILES tools/pico-wireless-config.py DESTINATION libexec/reframed-vr
            COMPONENT PicoWifiIdentity)
    configure_file(system/pico/reframed-pico-wifi-identity.in
                   reframed-pico-wifi-identity @ONLY)
    install(PROGRAMS "${CMAKE_CURRENT_BINARY_DIR}/reframed-pico-wifi-identity"
            DESTINATION libexec/reframed-vr COMPONENT PicoWifiIdentity)
    configure_file(system/pico/reframed-pico-wifi-identity@.service.in
                   reframed-pico-wifi-identity@.service @ONLY)
    install(FILES "${CMAKE_CURRENT_BINARY_DIR}/reframed-pico-wifi-identity@.service"
            DESTINATION lib/systemd/system COMPONENT PicoWifiIdentity)
    install(FILES system/pico/10-reframed-pico-wifi.link
            DESTINATION lib/systemd/network COMPONENT PicoWifiIdentity)
endif()

option(REFRAMED_PICO_BLUETOOTH_IDENTITY "Install native Pico Bluetooth identity startup" OFF)
if(REFRAMED_PICO_BLUETOOTH_IDENTITY)
    if(NOT CMAKE_SYSTEM_NAME STREQUAL "Linux")
        message(FATAL_ERROR "Pico Bluetooth identity startup requires Linux")
    endif()
    install(PROGRAMS tools/pico-bluetooth-identity.py DESTINATION libexec/reframed-vr
            COMPONENT PicoBluetoothIdentity)
    configure_file(system/pico/reframed-pico-bluetooth-identity.in
                   reframed-pico-bluetooth-identity @ONLY)
    install(PROGRAMS "${CMAKE_CURRENT_BINARY_DIR}/reframed-pico-bluetooth-identity"
            DESTINATION libexec/reframed-vr COMPONENT PicoBluetoothIdentity)
    configure_file(system/pico/reframed-pico-bluetooth-identity.service.in
                   reframed-pico-bluetooth-identity.service @ONLY)
    install(FILES "${CMAKE_CURRENT_BINARY_DIR}/reframed-pico-bluetooth-identity.service"
            DESTINATION lib/systemd/system COMPONENT PicoBluetoothIdentity)
endif()

option(REFRAMED_PICO_DESKTOP_TEST "Build the opt-in physical Pico desktop-layer test" OFF)
if(REFRAMED_PICO_DESKTOP_TEST)
    find_package(X11 REQUIRED)
    add_executable(pico-desktop-xr-test tests/pico-desktop-xr.cpp src/xr-renderer.cpp)
    target_include_directories(pico-desktop-xr-test PRIVATE src)
    target_compile_features(pico-desktop-xr-test PRIVATE cxx_std_17)
    target_compile_options(pico-desktop-xr-test PRIVATE -Wall -Wextra -Werror -Wno-missing-field-initializers)
    target_link_libraries(pico-desktop-xr-test PRIVATE OpenXR::openxr_loader Vulkan::Vulkan X11::X11 Threads::Threads)
endif()
