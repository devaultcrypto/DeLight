#!/usr/bin/ruby
require 'xcodeproj'
require 'plist'
require 'open3'

# These should be edited by each user, if password for dev_team is not available
bundle_id = "org.devault.DeLight";
dev_team = "MN42Q8L42Y";
#

project_path = "iOS/DeLight.xcodeproj";

# Create project object
project = Xcodeproj::Project.open(project_path);

stdout,stderr,status = Open3.capture3("/usr/bin/xcode-select -print-path")


if status
  lib = stdout.strip + '/Platforms/iPhoneOS.platform/Developer/SDKs/iPhoneOS.sdk/usr/lib/libxml2.tbd'
else
  puts "Xcode not found!"
  exit(1)
end

project.targets.each do |target|
  build_phase = target.frameworks_build_phase
  framework_group = project.frameworks_group
  file_ref = framework_group.new_reference(lib)
  build_file = build_phase.add_file_reference(file_ref)
  target.build_configurations.each do |config|
    config.build_settings["COPY_PHASE_STRIP"] =  "NO"
    config.build_settings["ENABLE_BITCODE"] =  "NO"
    config.build_settings["STRIP_INSTALLED_PRODUCT"] = "NO";
    config.build_settings["STRIP_STYLE"] = "debugging";
    config.build_settings["GCC_SYMBOLS_PRIVATE_EXTERN"] = "NO";
    config.build_settings["VALID_ARCHS"] = "arm64";
    config.build_settings["DEVELOPMENT_TEAM"] =  dev_team
    config.build_settings["BUNDLE_IDENTIFIER"] =  bundle_id
    config.build_settings["PRODUCT_BUNDLE_IDENTIFIER"] =  bundle_id
  end
end

# Save the project
project.save();

#Update plist file to be consistent

infoplist="iOS/ElectronCash/ElectronCash-Info.plist"
result = Plist.parse_xml(infoplist)
result['CFBundleIdentifier'] = bundle_id
result.save_plist(infoplist)

