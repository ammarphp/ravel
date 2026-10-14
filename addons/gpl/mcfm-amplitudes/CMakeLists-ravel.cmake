# SPDX-License-Identifier: GPL-3.0-or-later
# Include once at the END of the exact MCFM root CMakeLists.txt.
if(NOT CMAKE_C_COMPILER_ID STREQUAL "GNU" OR NOT CMAKE_CXX_COMPILER_ID STREQUAL "GNU" OR NOT CMAKE_Fortran_COMPILER_ID STREQUAL "GNU")
  message(FATAL_ERROR "This source-bound MCFM bridge requires GNU C/C++/Fortran")
endif()
if(use_mpi OR use_coarray)
  message(FATAL_ERROR "RAVEL bridge uses one process/thread, no MPI/coarrays")
endif()
target_sources(objlib PRIVATE ${CMAKE_SOURCE_DIR}/ravel/ravel_bridge.f90)
add_executable(ravel_mcfm_amplitudes ${CMAKE_SOURCE_DIR}/ravel/ravel_driver.f90 $<TARGET_OBJECTS:objlib>)
target_include_directories(ravel_mcfm_amplitudes PRIVATE ${CMAKE_SOURCE_DIR}/src/Inc ${CMAKE_SOURCE_DIR} ${CMAKE_BINARY_DIR} $<TARGET_PROPERTY:objlib,Fortran_MODULE_DIRECTORY>)
target_link_libraries(ravel_mcfm_amplitudes PRIVATE $<TARGET_PROPERTY:mcfm,LINK_LIBRARIES>)
set_property(TARGET ravel_mcfm_amplitudes PROPERTY INSTALL_RPATH "${CMAKE_BINARY_DIR}/local/lib")
install(TARGETS ravel_mcfm_amplitudes RUNTIME DESTINATION ${CMAKE_BINARY_DIR})
