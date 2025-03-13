import pytest

from vcenter_operator.templates import VCenterServiceUserCRDLoader, VCenterServiceUserCRDUsernameTemplateDuplicateError


@pytest.fixture
def vcenter_service_user_crd_loader():
    """Fixture to create a DeploymentState instance"""
    vcenter_service_user_crd_loader = VCenterServiceUserCRDLoader()

    return vcenter_service_user_crd_loader

def test_duplicate_service_username_template(vcenter_service_user_crd_loader):
    """Test the prevention of duplicate service username templates"""
    vcenter_service_user_crd_loader.mapping = {
        "test_service_user_template0001": ("1", "test_service_user_template", "test_namespace"),
    }

    with pytest.raises(VCenterServiceUserCRDUsernameTemplateDuplicateError):
        vcenter_service_user_crd_loader._check_service_username_template_exists(
            vcenter_service_user_crd_loader.mapping, "test_service_user_template")

def test_no_duplicate_service_username_template(vcenter_service_user_crd_loader):
    """Test the prevention of duplicate service username templates"""
    vcenter_service_user_crd_loader.mapping = {
        "test_service_user_template0001": ("1", "test_service_user_template", "test_namespace"),
    }

    try:
        vcenter_service_user_crd_loader._check_service_username_template_exists(
            vcenter_service_user_crd_loader.mapping, "unique_service_user_template")
    except VCenterServiceUserCRDUsernameTemplateDuplicateError:
        pytest.fail("Unexpected VCenterServiceUserCRDUsernameTemplateDuplicate raised for unique template")
